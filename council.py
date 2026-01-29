#!/usr/bin/env python3
"""
council - Multi-agent parallel deliberation with project context

Query multiple AI agents about a project, share responses, iterate to consensus.
Point it at any project directory for context-aware deliberation.

Usage:
    council -p ~/Projects/myapp "How should we refactor this?"
    council -p . -d "What's the best architecture?"
    council -p ~/Projects/council "How can this tool improve itself?"
"""

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
import tempfile
import subprocess

__version__ = "0.2.0"

# Agent configurations - ALL READ-ONLY (analysis only)
AGENTS = {
    "gemini": {
        "name": "Gemini",
        "cmd": ["gemini"],
        "description": "Google's Gemini - research, broad knowledge",
    },
    "claude": {
        "name": "Claude",
        "cmd": ["claude", "-p"],  # -p = print mode
        "description": "Anthropic's Claude - architecture, reasoning",
        "use_stdin": True,  # Claude needs stdin, not positional args
    },
    "codex": {
        "name": "Codex",
        "cmd": ["codex", "exec"],  # Default sandbox is read-only
        "description": "OpenAI's Codex - heavy engineering",
        "needs_git": True,
    },
    "kimi": {
        "name": "Kimi",
        "cmd": ["kimi", "--quiet", "-p"],  # --quiet = non-interactive print mode
        "description": "Moonshot's Kimi - UI/UX, frontend",
    },
}

COUNCIL_DIR = Path.home() / ".council"

# Files to read for project context
CONTEXT_FILES = [
    "README.md",
    "AGENTS.md",
    "package.json",
    "Cargo.toml",
    "pyproject.toml",
    "go.mod",
]

# Source patterns to sample
SOURCE_PATTERNS = ["*.py", "*.rs", "*.ts", "*.js", "*.go"]


def log(msg: str, end: str = "\n"):
    """Print with immediate flush."""
    print(msg, end=end, flush=True)


def gather_project_context(project_dir: Path, max_chars: int = 8000) -> str:
    """Gather context from a project directory."""
    context_parts = []
    chars_used = 0
    
    # Read key config/doc files
    for filename in CONTEXT_FILES:
        filepath = project_dir / filename
        if filepath.exists():
            try:
                content = filepath.read_text()[:2000]
                context_parts.append(f"### {filename}\n```\n{content}\n```\n")
                chars_used += len(content)
                if chars_used > max_chars:
                    break
            except:
                pass
    
    # List source files
    source_files = []
    for pattern in SOURCE_PATTERNS:
        source_files.extend(project_dir.rglob(pattern))
    
    # Filter out node_modules, target, etc.
    source_files = [f for f in source_files if not any(
        x in str(f) for x in ["node_modules", "target", ".git", "__pycache__", "dist"]
    )]
    
    if source_files:
        file_list = "\n".join(f"  - {f.relative_to(project_dir)}" for f in source_files[:30])
        context_parts.append(f"### Source Files\n{file_list}\n")
        
        # Sample main source file
        main_files = [f for f in source_files if f.name in ["main.py", "main.rs", "index.ts", "main.go", "council.py"]]
        if main_files and chars_used < max_chars:
            main = main_files[0]
            try:
                content = main.read_text()[:3000]
                context_parts.append(f"### {main.name} (main source)\n```\n{content}\n```\n")
            except:
                pass
    
    return "\n".join(context_parts) if context_parts else "[No project context found]"


async def query_agent(
    agent_id: str, 
    prompt: str, 
    project_dir: Optional[Path] = None,
    timeout: int = 600  # 10 minutes - agents should complete, not timeout
) -> dict:
    """Query a single agent, optionally with project context."""
    agent = AGENTS[agent_id]
    cmd = list(agent["cmd"])
    cwd = None
    use_stdin = agent.get("use_stdin", False)  # Some agents need stdin instead of args
    
    try:
        # Handle project-aware agents
        if project_dir and agent.get("project_aware"):
            if agent.get("workdir_flag"):
                cmd.extend([agent["workdir_flag"], str(project_dir)])
            else:
                cwd = project_dir
        
        # Codex needs a git repo
        if agent.get("needs_git"):
            if project_dir and (project_dir / ".git").exists():
                cwd = project_dir
            else:
                # Create temp git repo
                tmpdir = tempfile.mkdtemp()
                subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
                cwd = tmpdir
        
        # Some agents (Claude) work better with stdin than positional args
        if use_stdin:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout, stderr = await proc.communicate(input=prompt.encode())
        else:
            cmd.append(prompt)
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout, stderr = await proc.communicate()
        
        response = stdout.decode("utf-8", errors="replace").strip()
        return {
            "agent": agent_id,
            "name": agent["name"],
            "response": response,
            "success": proc.returncode == 0 and len(response) > 0,  # Any response = success
        }
    # No timeout - agents complete when ready
    except Exception as e:
        return {"agent": agent_id, "name": agent["name"], "response": "", "success": False, "error": str(e)}


def format_responses(responses: list[dict], exclude: str = None) -> str:
    """Format responses for cross-pollination."""
    parts = []
    for r in responses:
        if r["success"] and r["agent"] != exclude:
            # Truncate long responses
            text = r["response"][:2000]
            parts.append(f"### {r['name']}'s Analysis:\n{text}\n")
    return "\n---\n".join(parts)


def extract_choice(response: str) -> Optional[str]:
    """Extract which option the agent chose."""
    patterns = [
        r"(?:choose|pick|recommend|go with|select)\s+(?:option\s+)?([A-Z])",
        r"(?:option\s+)?([A-Z])\s+(?:is|would be)\s+(?:the\s+)?(?:best|right)",
        r"my\s+(?:recommendation|choice)\s*(?:is|:)\s*(?:option\s+)?([A-Z])",
        r"^([A-Z])\)",
    ]
    for pattern in patterns:
        match = re.search(pattern, response, re.IGNORECASE | re.MULTILINE)
        if match:
            return match.group(1).upper()
    return None


def check_consensus(responses: list[dict], min_votes: int = 2) -> tuple[bool, Optional[str], dict]:
    """Check for consensus among successful responses."""
    choices = {}
    for r in responses:
        if r["success"]:
            choice = extract_choice(r["response"])
            if choice:
                choices[r["agent"]] = choice
    
    if len(choices) < min_votes:
        return False, None, choices
    
    if len(set(choices.values())) == 1:
        return True, list(choices.values())[0], choices
    
    return False, None, choices


async def deliberate(
    question: str, 
    agents: list[str], 
    project_dir: Optional[Path] = None,
    max_rounds: int = 3
) -> dict:
    """Run multi-round deliberation until consensus."""
    
    # Gather project context
    context = ""
    if project_dir:
        log(f"📂 Reading project: {project_dir}")
        context = gather_project_context(project_dir)
        log(f"   Found {len(context)} chars of context")
    
    log(f"\n🏛️  COUNCIL DELIBERATION")
    log(f"{'═' * 60}")
    log(f"Question: {question[:80]}{'...' if len(question) > 80 else ''}")
    log(f"Agents: {', '.join(agents)}")
    log(f"Rounds: {max_rounds}")
    if project_dir:
        log(f"Project: {project_dir}")
    log(f"{'═' * 60}\n")
    
    all_rounds = []
    consensus_reached = False
    consensus_choice = None
    
    for round_num in range(1, max_rounds + 1):
        log(f"\n{'─' * 60}")
        log(f"🔄 ROUND {round_num}")
        log(f"{'─' * 60}")
        
        prompts = {}
        if round_num == 1:
            base = f"""COUNCIL DELIBERATION - Round 1

PROJECT CONTEXT:
{context if context else "[No project specified]"}

QUESTION:
{question}

You are one of several AI advisors deliberating on this question.
Analyze the project/question and provide your recommendation.

If this involves choosing between options, end with: "My recommendation: Option X"

Other advisors will see your response and may agree or challenge it."""
            prompts = {a: base for a in agents}
        else:
            prev = all_rounds[-1]["responses"]
            for agent_id in agents:
                others = format_responses(prev, exclude=agent_id)
                my_prev = next((r for r in prev if r["agent"] == agent_id), None)
                my_text = my_prev["response"][:1000] if my_prev and my_prev["success"] else "[No response]"
                
                prompts[agent_id] = f"""COUNCIL DELIBERATION - Round {round_num}

PROJECT CONTEXT:
{context if context else "[No project]"}

ORIGINAL QUESTION:
{question}

YOUR PREVIOUS POSITION:
{my_text}

OTHER ADVISORS' POSITIONS:
{others}

Consider your colleagues' perspectives:
1. What do you AGREE with from their analysis?
2. What do you DISAGREE with or want to challenge?
3. What is your REFINED recommendation?

End with: "My recommendation: ..." """

        # Query all agents in parallel
        log(f"⏳ Querying {len(agents)} agents in parallel...")
        tasks = [query_agent(a, prompts[a], project_dir) for a in agents]
        responses = await asyncio.gather(*tasks)
        
        # Display
        for r in responses:
            choice = extract_choice(r["response"]) if r["success"] else None
            status = "✅" if r["success"] else "❌"
            choice_str = f" → {choice}" if choice else ""
            log(f"\n{status} {r['name']}{choice_str}")
            log("─" * 40)
            if r["success"]:
                text = r["response"][:1500] + "\n..." if len(r["response"]) > 1500 else r["response"]
                log(text)
            else:
                log(f"Error: {r.get('error', 'Unknown')}")
        
        all_rounds.append({"round": round_num, "responses": responses})
        
        # Check consensus
        consensus_reached, consensus_choice, choices = check_consensus(responses)
        log(f"\n📊 Positions: {choices}")
        
        if consensus_reached:
            log(f"\n🎉 CONSENSUS REACHED: {consensus_choice}")
            break
        elif round_num < max_rounds:
            log(f"⚡ No consensus yet, proceeding to round {round_num + 1}...")
    
    # Final
    log(f"\n{'═' * 60}")
    if consensus_reached:
        log(f"✅ FINAL CONSENSUS: {consensus_choice}")
    else:
        _, _, final = check_consensus(all_rounds[-1]["responses"])
        log(f"⚠️  NO CONSENSUS after {max_rounds} rounds")
        log(f"Final positions: {final}")
    log(f"{'═' * 60}")
    
    # Save
    session = {
        "version": __version__,
        "timestamp": datetime.now().isoformat(),
        "question": question,
        "project": str(project_dir) if project_dir else None,
        "agents": agents,
        "rounds": all_rounds,
        "consensus": consensus_reached,
        "consensus_choice": consensus_choice,
    }
    
    COUNCIL_DIR.mkdir(exist_ok=True)
    session_file = COUNCIL_DIR / f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(session_file, "w") as f:
        json.dump(session, f, indent=2)
    log(f"\n📁 Session: {session_file}\n")
    
    return session


async def quick_query(prompt: str, agents: list[str], project_dir: Optional[Path] = None) -> dict:
    """Quick parallel query without deliberation."""
    context = gather_project_context(project_dir) if project_dir else ""
    
    full_prompt = f"""PROJECT CONTEXT:
{context if context else "[No project]"}

QUESTION:
{prompt}

Provide your analysis and recommendation."""

    log(f"\n🏛️  QUICK QUERY")
    log("─" * 50)
    if project_dir:
        log(f"Project: {project_dir}")
    log(f"Question: {prompt[:80]}...")
    log("─" * 50 + "\n")
    
    log(f"⏳ Querying {len(agents)} agents...")
    tasks = [query_agent(a, full_prompt, project_dir) for a in agents]
    responses = await asyncio.gather(*tasks)
    
    for r in responses:
        status = "✅" if r["success"] else "❌"
        log(f"\n{status} {r['name']}")
        log("─" * 40)
        log(r["response"][:2000] if r["success"] else f"Error: {r.get('error')}")
    
    log("")
    return {"responses": responses}


def main():
    parser = argparse.ArgumentParser(
        description="Multi-agent deliberation with project context",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Quick query about a project
  council -p ~/Projects/myapp "How should we refactor the auth module?"

  # Full deliberation
  council -p . -d "What architecture should we use?"

  # Meta: council improves itself
  council -p ~/Projects/council -d "How can this tool improve itself?"

  # Multiple agents, more rounds
  council -p . -d -r 4 -a gemini,claude,codex,kimi "Review the codebase"
"""
    )
    parser.add_argument("prompt", nargs="?", help="Question for the council")
    parser.add_argument("-p", "--project", type=Path, help="Project directory for context")
    parser.add_argument("-a", "--agents", default="gemini,claude", help="Comma-separated agents")
    parser.add_argument("-d", "--deliberate", action="store_true", help="Enable multi-round deliberation")
    parser.add_argument("-r", "--rounds", type=int, default=3, help="Max deliberation rounds")
    parser.add_argument("-l", "--list", action="store_true", help="List available agents")
    parser.add_argument("-v", "--version", action="version", version=f"council {__version__}")
    
    args = parser.parse_args()
    
    if args.list:
        log("\n🏛️  AVAILABLE AGENTS\n")
        for aid, a in AGENTS.items():
            proj = "📂" if a.get("project_aware") else "  "
            log(f"  {proj} {aid}: {a['description']}")
        log("\n  📂 = runs in project directory\n")
        return 0
    
    if not args.prompt:
        parser.print_help()
        return 1
    
    agents = [a.strip() for a in args.agents.split(",") if a.strip() in AGENTS]
    if not agents:
        log("Error: No valid agents. Use -l to list available agents.")
        return 1
    
    project_dir = args.project.resolve() if args.project else None
    if project_dir and not project_dir.exists():
        log(f"Error: Project directory not found: {project_dir}")
        return 1
    
    try:
        if args.deliberate:
            asyncio.run(deliberate(args.prompt, agents, project_dir, args.rounds))
        else:
            asyncio.run(quick_query(args.prompt, agents, project_dir))
    except KeyboardInterrupt:
        log("\n\nDeliberation cancelled.")
        return 130
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
