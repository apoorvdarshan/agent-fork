# agent-fork

Continue an AI coding chat in another agent. Fork a chat between **Claude Code**,
**Codex**, and **OpenCode** in any direction. The new chat opens in a new terminal
tab in the same folder with the conversation already in its history.

```
in Claude Code:   /agent-fork codex
                        │
                        ▼
  reads this Claude chat → writes it as a native Codex chat
                        │
                        ▼
  new tab (same folder): codex resume <new id>  → full chat is there
```

Common uses: you hit one agent's usage limit, you want a second opinion from a
different model, or you want to try something without touching the original chat.

## Use it

Inside a chat, either:

- **Ask for it (skill):** type `/agent-fork codex` in Claude Code, or say
  "fork this chat to opencode" in any of the three. The agent runs the command.
- **Run it yourself (no AI step):** type `!agent-fork codex`. The `!` runs it as
  a shell command.

From a normal terminal, `agent-fork codex` forks the latest chat in the
current folder.

| Command | Result |
|---|---|
| `agent-fork` | copy of this chat in the same agent |
| `agent-fork codex` | continue this chat in Codex |
| `agent-fork claude` | continue this chat in Claude Code |
| `agent-fork opencode` | continue this chat in OpenCode |
| `agent-fork --list` | recent chats in this folder, per agent |

Options: `--split` (split pane instead of tab), `--workspace` (new cmux
workspace), `--no-open` (only print the command), `--no-focus` (don't switch
to the new tab), `--tools short|full|none` (how much tool history to carry,
default `short`), `--from` / `--session` (pick the source chat yourself).

## How it works

- **Same agent:** uses that agent's own fork (`claude --resume <id> --fork-session`,
  `codex fork <id>`, or an OpenCode export/import under new ids).
- **Different agent:** reads the chat and writes it in the target's own session
  format, so it appears as normal history rather than one pasted message.
  - Claude Code: reads and writes `~/.claude/projects/<folder>/<id>.jsonl`.
  - Codex: reads through `codex app-server`, writes a session file under
    `~/.codex/sessions/`.
  - OpenCode: `opencode session export` / `opencode session import`.
- Your messages and the agent's replies are carried over as they were. Tool
  calls are carried as text, marked as already done, with long output trimmed.
  Hidden reasoning is left out.
- The current chat is detected automatically: the agent this command runs inside
  plus its session id (`CLAUDE_CODE_SESSION_ID`, `CODEX_THREAD_ID`,
  `OPENCODE_SESSION_ID`).
- Tabs open in [cmux](https://cmux.com), tmux, iTerm2, or Terminal.app. Anywhere
  else it prints the command to run.

Copying makes no AI calls. Credits are only used by what you do in the new chat,
plus, if you go through the skill, the agent's short step of running the command.
Claude Code also replies briefly after a `!` command.

## Install

Needs Python 3.9+ and whichever of `claude`, `codex`, `opencode` you use.

```sh
curl -fsSL https://raw.githubusercontent.com/apoorvdarshan/agent-fork/main/install.sh | sh
```

or from a clone: `./install.sh`. This installs `~/.local/bin/agent-fork` and the
`agent-fork` skill for Claude Code (`~/.claude/skills`), Codex (`~/.codex/skills`),
OpenCode (`~/.config/opencode/skills`), and `~/.agents/skills`. Make sure
`~/.local/bin` is on your `PATH`. Restart running agents to pick up the skill.

## Limits

- Built against Claude Code 2.1, Codex 0.162, and OpenCode 2.0. These session
  formats are not public APIs and may change.
- Very long chats are copied in full; the target agent compacts them as needed.
- Codex chats in the older (legacy) format carry messages but not tool calls.
