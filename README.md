# Council

Multi-agent consultation tool. Get second opinions from AI advisors.

## Usage

```bash
# Basic query
council "What's the best architecture for a CAD application?"

# Specify agents
council --agents gemini,claude,codex "Review this system design"

# Include context from a file
council --context-file spec.md "Critique this specification"

# List available agents
council --list
```

## Available Agents

| Agent | Strengths |
|-------|-----------|
| **gemini** | Research, broad knowledge, Google ecosystem |
| **claude** | Architecture, clean code, documentation |
| **codex** | Heavy engineering, complex code, system design |

## How It Works

1. Your question is sent to all selected agents in parallel
2. Each agent provides their perspective
3. Responses are displayed and saved to `~/.council/`
4. You (or an orchestrator) synthesize the insights

## Output

Sessions are saved as JSON to `~/.council/session_YYYYMMDD_HHMMSS.json`

```json
{
  "timestamp": "2026-01-29T12:00:00",
  "prompt": "Your question",
  "responses": [
    {
      "agent": "gemini",
      "name": "Gemini",
      "response": "...",
      "success": true
    }
  ]
}
```

## Installation

```bash
# Make executable
chmod +x council.py

# Add to path (optional)
ln -s ~/Projects/council/council.py ~/.local/bin/council
```

## Requirements

- Python 3.10+
- Gemini CLI (`gemini`)
- Claude Code CLI (`claude`)
- Codex CLI (`codex`) - optional
