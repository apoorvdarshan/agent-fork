---
name: agent-fork
description: Fork the current chat into another coding agent (Claude Code, Codex, OpenCode, GitHub Copilot, Cursor, Gemini CLI, Qwen Code, Factory Droid, Kiro, Cline, Kilo Code, Pi, Auggie, Amp, Goose, Kimi, Mistral Vibe, Junie, Qoder, OpenHands, Crush, Devin, Hermes, OpenClaw, Antigravity) and open it in a new terminal tab in the same folder with the conversation carried over. Use when the user asks to fork this chat, continue it in another agent, move or switch it to another agent, or hand it off (for example because of usage limits).
---

# agent-fork

1. Pick the target agent from the user's words: `claude`, `codex`, `opencode`,
   `copilot`, `cursor`, `gemini`, `qwen`, `droid`, `kiro`, `cline`, `kilo`, `pi`,
   `auggie`, `amp`, `goose`, `kimi`, `vibe`, `junie`, `qoder`, `openhands`,
   `crush`, `devin`, `hermes`, `openclaw`, `antigravity`. If no agent is named,
   leave it out to make a copy in the current agent.
2. From the current working directory, run:

   ```sh
   python3 ~/.agents/skills/agent-fork/scripts/agent_fork.py <target> --via-skill
   ```

   If that file doesn't exist, run `scripts/agent_fork.py` from the folder that
   holds this SKILL.md. Add `--split` only if the user asks for a split.
3. If the output starts with `NEED_HANDOFF`, this agent's chat can't be read from
   disk. Do exactly what it says: write the whole conversation to the file it
   names, then run the command it prints.
4. Reply with one short line based on the output, for example "Forked to Codex.
   It's open in a new tab." If it says the chat is on the clipboard, tell the user
   to paste it into the new tab. Don't run it twice or start other work.
