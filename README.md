# agent-fork

A skill that forks your current AI coding chat into another coding agent. The
new chat opens in a new terminal tab, in the same folder, with the conversation
carried over.

```
in Claude Code:  /agent-fork codex
                       │
                       ▼
   the skill copies this chat into Codex's own session format
                       │
                       ▼
   new tab, same folder: Codex opens with the whole chat in its history
```

Useful when one agent hits its usage limit, when you want a second opinion from
another model, or when you want to try something without touching the original.

## Use it

Ask the agent, in any chat:

- Claude Code: `/agent-fork codex`
- Most agents: "fork this chat to opencode", "continue this in gemini", "move
  this to claude"
- No agent named: makes a copy in the same agent.

## Supported agents

**Real history** (the chat shows up as normal messages in the new agent):

| From \ To | Claude Code | Codex | OpenCode |
|---|---|---|---|
| Claude Code | ✓ (own fork) | ✓ | ✓ |
| Codex | ✓ | ✓ (own fork) | ✓ |
| OpenCode | ✓ | ✓ | ✓ (own fork) |

**Handoff** for every other agent. The new agent starts with the earlier chat as
its first message and replies that it's ready.

- Starts with the chat directly: GitHub Copilot, Cursor, Gemini CLI, Qwen Code,
  Factory Droid, Kiro, Cline, Kilo Code, Pi, Auggie, Goose, Mistral Vibe,
  OpenHands, Devin, Hermes, OpenClaw.
- Opens normally with the chat on your clipboard to paste: Amp, Kimi, Junie,
  Qoder, Crush, Antigravity.

Forking *from* one of these agents works too. Their chats can't be read from
disk, so the agent writes a summary of the conversation first, and that summary
becomes the handoff.

Tested on macOS with Claude Code 2.1, Codex 0.162 and OpenCode 2.0, including
the handoff path. The other agents' launch flags come from their docs and
haven't been tested here.

## Install

Needs Python 3.9+.

```sh
curl -fsSL https://raw.githubusercontent.com/apoorvdarshan/agent-fork/main/install.sh | sh
```

or from a clone: `./install.sh`. The skill goes to `~/.agents/skills/agent-fork`
and is linked into the skills folder of each agent that is set up on the machine
(`~/.claude/skills`, `~/.codex/skills`, `~/.config/opencode/skills`,
`~/.copilot/skills`, `~/.cursor/skills`, `~/.gemini/skills`, and so on).
Restart running agents to pick it up.

## How it works

The skill runs `scripts/agent_fork.py`, which:

1. Finds the agent it was started from (from the process tree) and that agent's
   current session (`CLAUDE_CODE_SESSION_ID`, `CODEX_THREAD_ID`,
   `OPENCODE_SESSION_ID`).
2. Reads the chat:
   - Claude Code: `~/.claude/projects/<folder>/<id>.jsonl`
   - Codex: through `codex app-server`
   - OpenCode: `opencode session export`
   - other agents: a handoff file the agent writes
3. Writes it for the target:
   - Claude Code, Codex, OpenCode: a new session in their own format
   - same agent: its own fork (`claude --resume <id> --fork-session`,
     `codex fork <id>`, or an OpenCode copy)
   - others: the first message of a new session
4. Opens it in a new tab with [cmux](https://cmux.com), tmux, iTerm2 or
   Terminal.app. Anywhere else it prints the command to run.

What gets carried over: your messages and the agent's replies as they were.
Tool calls come along as text, marked as already done, with long output trimmed.
Hidden reasoning is left out. Handoffs are capped at about 300,000 characters,
keeping the newest messages, and a copy is kept in `~/.cache/agent-fork` for a
week.

Options (the agent can pass them when you ask): `--split`, `--workspace` (cmux),
`--no-focus`, `--no-open`, `--tools short|full|none`.

## Limits

- Session formats aren't public APIs and can change between agent versions.
- Older (legacy) Codex chats carry messages but not tool calls.
- A handoff uses some AI credit in the new agent, for its "ready" reply.
  Running the skill uses a little in the current agent.
