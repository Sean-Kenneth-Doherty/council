# Council 🏛️

Multi-agent AI deliberation tool. Get multiple perspectives, iterate toward consensus.

## What It Does

Council queries multiple AI agents in parallel, shares their responses with each other, and iterates until they reach consensus (or max rounds). Perfect for:

- **Architecture decisions** - "Should we use Rust or Go?"
- **Code reviews** - Get diverse perspectives on a design
- **Strategic planning** - Explore options with different viewpoints
- **Second opinions** - Never rely on a single AI's take

## How It Works

```
Round 1: All agents respond independently (parallel)
    ↓
Round 2: Each agent sees OTHER agents' responses
         "Here's what Gemini said... do you agree?"
         All respond in parallel
    ↓
Round 3: Same pattern, positions refine
    ↓
Check: Did they converge on the same option?
    ↓
Output: Consensus reached, or final vote tally
```

Key insight: each agent sees **all others** but **not their own prior response** to avoid echo chambers.

## Installation

```bash
# Clone
git clone https://github.com/yourusername/council.git
cd council

# Make executable
chmod +x council.py

# Add to PATH (optional)
ln -s $(pwd)/council.py ~/.local/bin/council
```

### Requirements

- Python 3.10+
- At least one of these AI CLIs:
  - `gemini` - [Gemini CLI](https://github.com/google-gemini/gemini-cli)
  - `claude` - [Claude Code](https://github.com/anthropics/claude-code)
  - `codex` - [Codex CLI](https://github.com/openai/codex)

## Usage

### Quick Query (Parallel, No Deliberation)

```bash
council "What's the best database for a real-time analytics app?"
```

### Full Deliberation (Multi-Round Consensus)

```bash
council -d "Should we use Rust or Go for this backend service?"
```

### Options

```
council [options] "Your question"

Options:
  -d, --deliberate     Enable multi-round deliberation
  -r, --rounds N       Max deliberation rounds (default: 3)
  -a, --agents LIST    Comma-separated agents (default: gemini,claude)
  -c, --context TEXT   Additional context
  -l, --list           List available agents
  -v, --version        Show version
```

### Examples

```bash
# Quick parallel query
council "What's the best way to handle authentication?"

# Full deliberation with 3 rounds
council -d -r 3 "For a CAD app: A) Web Three.js, B) Rust/Tauri, or C) Rust WASM + Web?"

# Specific agents
council -d -a gemini,codex "Review this API design..."

# With context
council -d -c "We have 2 developers, 3 month timeline" "Monolith or microservices?"
```

## Available Agents

| Agent | CLI | Strengths |
|-------|-----|-----------|
| `gemini` | `gemini` | Research, broad knowledge, up-to-date info |
| `claude` | `claude` | Architecture, reasoning, documentation |
| `codex` | `codex` | Heavy engineering, complex systems |

## Session Logs

All deliberations are saved to `~/.council/` as JSON:

```json
{
  "timestamp": "2026-01-29T12:30:00",
  "question": "Your question",
  "agents": ["gemini", "claude"],
  "rounds": [...],
  "consensus": true,
  "consensus_choice": "C"
}
```

## Extending

Adding a new agent is simple - just add an entry to the `AGENTS` dict:

```python
AGENTS["myagent"] = {
    "name": "My Agent",
    "cmd": ["myagent", "--flag"],
    "description": "What it's good at",
}
```

## License

MIT

## Credits

Built for the [Clawdbot](https://github.com/clawdbot/clawdbot) agentic engineering ecosystem.
