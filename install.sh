#!/bin/sh
# Install the agent-fork skill into ~/.agents/skills, then link it into the
# skills folder of every coding agent that is set up on this machine.
set -eu

REPO_RAW="https://raw.githubusercontent.com/apoorvdarshan/agent-fork/main"
SKILL_HOME="$HOME/.agents/skills/agent-fork"
CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}"

here=$(cd "$(dirname "$0")" 2>/dev/null && pwd || true)
mkdir -p "$HOME/.agents/skills"

if [ -n "$here" ] && [ -f "$here/skills/agent-fork/SKILL.md" ]; then
  # From a clone: link, so `git pull` updates the skill everywhere.
  if [ ! -e "$SKILL_HOME" ] || [ -L "$SKILL_HOME" ]; then
    ln -sfn "$here/skills/agent-fork" "$SKILL_HOME"
  fi
else
  mkdir -p "$SKILL_HOME/scripts"
  curl -fsSL "$REPO_RAW/skills/agent-fork/SKILL.md" -o "$SKILL_HOME/SKILL.md"
  curl -fsSL "$REPO_RAW/skills/agent-fork/scripts/agent_fork.py" -o "$SKILL_HOME/scripts/agent_fork.py"
  chmod +x "$SKILL_HOME/scripts/agent_fork.py"
fi
echo "skill  -> $SKILL_HOME"

# "<agent config folder>|<skills folder>": linked only when the agent is set up.
for pair in \
  "$HOME/.claude|$HOME/.claude/skills" \
  "$HOME/.codex|$HOME/.codex/skills" \
  "$CONFIG/opencode|$CONFIG/opencode/skills" \
  "$HOME/.copilot|$HOME/.copilot/skills" \
  "$HOME/.cursor|$HOME/.cursor/skills" \
  "$HOME/.gemini|$HOME/.gemini/skills" \
  "$HOME/.qwen|$HOME/.qwen/skills" \
  "$HOME/.factory|$HOME/.factory/skills" \
  "$HOME/.kiro|$HOME/.kiro/skills" \
  "$HOME/.cline|$HOME/.cline/skills" \
  "$CONFIG/kilo|$CONFIG/kilo/skills" \
  "$HOME/.pi/agent|$HOME/.pi/agent/skills" \
  "$HOME/.augment|$HOME/.augment/skills" \
  "$CONFIG/amp|$CONFIG/agents/skills" \
  "$CONFIG/goose|$CONFIG/goose/skills" \
  "$HOME/.kimi|$HOME/.kimi/skills" \
  "$HOME/.vibe|$HOME/.vibe/skills" \
  "$HOME/.junie|$HOME/.junie/skills" \
  "$HOME/.qoder|$HOME/.qoder/skills" \
  "$HOME/.openhands|$HOME/.openhands/skills" \
  "$CONFIG/crush|$CONFIG/crush/skills" \
  "$HOME/.devin|$HOME/.devin/skills" \
  "$HOME/.hermes|$HOME/.hermes/skills" \
  "$HOME/.openclaw|$HOME/.openclaw/skills"
do
  agent_dir=${pair%%|*}
  skills_dir=${pair#*|}
  [ -d "$agent_dir" ] || continue
  mkdir -p "$skills_dir"
  if [ ! -e "$skills_dir/agent-fork" ] || [ -L "$skills_dir/agent-fork" ]; then
    ln -sfn "$SKILL_HOME" "$skills_dir/agent-fork"
    echo "linked -> $skills_dir/agent-fork"
  fi
done
echo "Restart running agents to pick up the skill."
