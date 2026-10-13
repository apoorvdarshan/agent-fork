---
name: agent-fork
description: Fork the current chat into Claude Code, Codex, or OpenCode and open it in a new terminal tab in the same folder, with the full conversation carried over. Use when the user asks to fork this chat, continue it in another agent, move or switch it to Claude/Codex/OpenCode, or hand it off (for example because they are running out of credits).
---

# Fork this chat

Run the `agent-fork` command once. It finds the current chat by itself, copies it into
the target agent's own history format, and opens it in a new terminal tab.

1. Pick the target from the user's words:
   - Claude / Claude Code -> `claude`
   - Codex -> `codex`
   - OpenCode -> `opencode`
   - no agent named -> leave it out (makes a copy in the current agent)
2. Run exactly one shell command from the current working directory:

   ```sh
   agent-fork <target>
   ```

   Do not add `--session` or `--from`; detection is automatic. Add `--split` only
   if the user asks for a split instead of a tab.
3. Reply with one short line based on what it printed, such as
   "Forked to Codex. It's open in a new tab." Do not summarize the chat, start
   other work, or run the command again.

If the shell says `agent-fork: command not found`, tell the user to install it from
https://github.com/apoorvdarshan/agent-fork. If `agent-fork` prints an error, show
that error.
