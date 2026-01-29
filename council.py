#!/usr/bin/env python3
"""
council - Multi-agent parallel deliberation with consensus

Query multiple AI agents, share responses between them, iterate until consensus.
Perfect for architecture decisions, code reviews, and strategic planning.

Usage:
    council "Your question"                    # Quick parallel query
    council -d "Your question"                 # Full deliberation with consensus
    council -d -r 3 -a gemini,claude "..."     # 3 rounds, specific agents
"""

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
import tempfile

__version__ = "0.1.0"

# Agent configurations
AGENTS = {
    "gemini": {
        "name": "Gemini",
        "cmd": ["gemini"],
        "description": "Google's Gemini - strong at research and broad knowledge",
    },
    "claude": {
        "name": "Claude",
        "cmd": ["claude", "-p"],
        "description": "Anthropic's Claude - strong at architecture and reasoning",
    },
    "codex": {
        "name": "Codex",
        "cmd": ["codex", "exec"],
        "description": "OpenAI's Codex - strong at complex engineering",
        "needs_git": True,
    },
}

COUNCIL_DIR = Path.home() / ".council"


def log(msg: str, end: str = "\n"):
    """Print with immediate flush."""
    print(msg, end=end, flush=True)


async def query_agent(agent_id: str, prompt: str, timeout: int = 180) -> dict:
    """Query a single agent and return its response."""
    agent = AGENTS[agent_id]
    
    try:
        if agent.get("needs_git"):
            # Codex needs a git repo
            with tempfile.TemporaryDirectory() as tmpdir:
                await asyncio.create_subprocess_exec(
                    "git", "init", cwd=tmpdir,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                proc = await asyncio.create_subprocess_exec(
                    *agent["cmd"], prompt,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=tmpdir,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        else:
            proc = await asyncio.create_subprocess_exec(
                *agent["cmd"], prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        
        response = stdout.decode("utf-8", errors="replace").strip()
        return {
            "agent": agent_id,
            "name": agent["name"],
            "response": response,
            "success": proc.returncode == 0 and len(response) > 50,
        }
    except asyncio.TimeoutError:
        return {"agent": agent_id, "name": agent["name"], "response": "", "success": False, "error": "Timeout"}
    except Exception as e:
        return {"agent": agent_id, "name": agent["name"], "response": "", "success": False, "error": str(e)}


def format_responses(responses: list[dict], exclude: str = None) -> str:
    """Format responses for sharing between agents."""
    parts = []
    for r in responses:
        if r["success"] and r["agent"] != exclude:
            parts.append(f"### {r['name']}'s Position:\n{r['response']}\n")
    return "\n---\n".join(parts)


def extract_choice(response: str) -> Optional[str]:
    """Extract which option (A, B, C, etc.) the agent chose."""
    patterns = [
        r"(?:choose|pick|recommend|go with|select)\s+(?:option\s+)?([A-Z])",
        r"(?:option\s+)?([A-Z])\s+(?:is|would be)\s+(?:the\s+)?(?:best|right|correct)",
        r"my\s+(?:recommendation|choice|pick)\s*(?:is|:)\s*(?:option\s+)?([A-Z])",
        r"^([A-Z])\)",
    ]
    for pattern in patterns:
        match = re.search(pattern, response, re.IGNORECASE | re.MULTILINE)
        if match:
            return match.group(1).upper()
    return None


def check_consensus(responses: list[dict], min_votes: int = 2) -> tuple[bool, Optional[str], dict]:
    """Check if agents have reached consensus."""
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


async def deliberate(question: str, agents: list[str], max_rounds: int = 3, context: str = "") -> dict:
    """
    Run parallel deliberation until consensus or max rounds.
    
    Each round:
    1. All agents query in parallel
    2. Each agent sees OTHER agents' responses
    3. Check for consensus
    4. Repeat if no consensus
    """
    log(f"\n🏛️  COUNCIL DELIBERATION")
    log(f"{'═' * 60}")
    log(f"Question: {question[:80]}{'...' if len(question) > 80 else ''}")
    log(f"Agents: {', '.join(agents)}")
    log(f"Max Rounds: {max_rounds}")
    log(f"{'═' * 60}\n")
    
    all_rounds = []
    consensus_reached = False
    consensus_choice = None
    
    for round_num in range(1, max_rounds + 1):
        log(f"\n{'─' * 60}")
        log(f"🔄 ROUND {round_num}")
        log(f"{'─' * 60}")
        
        # Build prompts
        prompts = {}
        if round_num == 1:
            base = f"""COUNCIL DELIBERATION - Round 1

You are an AI advisor deliberating on this question:

{question}

{f"Context: {context}" if context else ""}

Provide your analysis and recommendation. Be SPECIFIC about which option you choose and why.
End with: "My recommendation: Option X"

Other advisors will see your response and may agree or challenge it."""
            prompts = {a: base for a in agents}
        else:
            prev = all_rounds[-1]["responses"]
            for agent_id in agents:
                others = format_responses(prev, exclude=agent_id)
                my_prev = next((r for r in prev if r["agent"] == agent_id), None)
                my_text = my_prev["response"][:800] if my_prev and my_prev["success"] else "[No response]"
                
                prompts[agent_id] = f"""COUNCIL DELIBERATION - Round {round_num}

Original Question: {question}

YOUR PREVIOUS POSITION:
{my_text}

OTHER ADVISORS' POSITIONS:
{others}

Considering your colleagues' perspectives:
1. What do you AGREE with?
2. What do you DISAGREE with?
3. What is your REFINED position?

End with: "My recommendation: Option X" """

        # Query all agents in parallel
        log(f"⏳ Querying {len(agents)} agents in parallel...")
        tasks = [query_agent(a, prompts[a]) for a in agents]
        responses = await asyncio.gather(*tasks)
        
        # Display responses
        for r in responses:
            choice = extract_choice(r["response"]) if r["success"] else None
            status = "✅" if r["success"] else "❌"
            choice_str = f" → Option {choice}" if choice else ""
            log(f"\n{status} {r['name']}{choice_str}")
            log("─" * 40)
            if r["success"]:
                text = r["response"][:1200] + "\n..." if len(r["response"]) > 1200 else r["response"]
                log(text)
            else:
                log(f"Error: {r.get('error', 'Unknown')}")
        
        all_rounds.append({"round": round_num, "responses": responses})
        
        # Check consensus
        consensus_reached, consensus_choice, choices = check_consensus(responses)
        log(f"\n📊 Choices: {choices}")
        
        if consensus_reached:
            log(f"\n🎉 CONSENSUS: Option {consensus_choice}")
            break
        elif round_num < max_rounds:
            log(f"⚡ No consensus, continuing to round {round_num + 1}...")
    
    # Final result
    log(f"\n{'═' * 60}")
    if consensus_reached:
        log(f"✅ FINAL CONSENSUS: Option {consensus_choice}")
    else:
        _, _, final = check_consensus(all_rounds[-1]["responses"])
        log(f"⚠️  NO CONSENSUS after {max_rounds} rounds")
        log(f"Final positions: {final}")
    log(f"{'═' * 60}")
    
    # Save session
    session = {
        "version": __version__,
        "timestamp": datetime.now().isoformat(),
        "question": question,
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


async def quick_query(prompt: str, agents: list[str]) -> dict:
    """Quick parallel query without deliberation."""
    log(f"\n🏛️  QUICK QUERY")
    log("─" * 50)
    log(f"Question: {prompt[:80]}...")
    log("─" * 50 + "\n")
    
    log(f"⏳ Querying {len(agents)} agents...")
    tasks = [query_agent(a, prompt) for a in agents]
    responses = await asyncio.gather(*tasks)
    
    for r in responses:
        status = "✅" if r["success"] else "❌"
        log(f"\n{status} {r['name']}")
        log("─" * 40)
        log(r["response"][:1500] if r["success"] else f"Error: {r.get('error')}")
    
    log("")
    return {"responses": responses}


def main():
    parser = argparse.ArgumentParser(
        description="Multi-agent deliberation tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  council "What's the best database for this use case?"
  council -d "Should we use Rust or Go for the backend?"
  council -d -r 3 -a gemini,claude,codex "Review this architecture"
"""
    )
    parser.add_argument("prompt", nargs="?", help="Question for the council")
    parser.add_argument("-a", "--agents", default="gemini,claude", help="Comma-separated agents")
    parser.add_argument("-d", "--deliberate", action="store_true", help="Enable multi-round deliberation")
    parser.add_argument("-r", "--rounds", type=int, default=3, help="Max deliberation rounds")
    parser.add_argument("-c", "--context", help="Additional context")
    parser.add_argument("-l", "--list", action="store_true", help="List available agents")
    parser.add_argument("-v", "--version", action="version", version=f"council {__version__}")
    
    args = parser.parse_args()
    
    if args.list:
        log("\n🏛️  AVAILABLE AGENTS\n")
        for aid, a in AGENTS.items():
            log(f"  {aid}: {a['description']}")
        log("")
        return 0
    
    if not args.prompt:
        parser.print_help()
        return 1
    
    agents = [a.strip() for a in args.agents.split(",") if a.strip() in AGENTS]
    if not agents:
        log("Error: No valid agents specified. Use -l to list available agents.")
        return 1
    
    try:
        if args.deliberate:
            asyncio.run(deliberate(args.prompt, agents, args.rounds, args.context or ""))
        else:
            asyncio.run(quick_query(args.prompt, agents))
    except KeyboardInterrupt:
        log("\n\nDeliberation cancelled.")
        return 130
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
