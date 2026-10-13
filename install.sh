#!/bin/sh
# Install agent-fork: the command into ~/.local/bin and the skill for
# Claude Code, Codex, OpenCode, and ~/.agents/skills.
set -eu

REPO_RAW="https://raw.githubusercontent.com/apoorvdarshan/agent-fork/main"
BIN_DIR="${AGENT_FORK_BIN_DIR:-$HOME/.local/bin}"
SKILL_HOME="$HOME/.agents/skills/agent-fork"

here=$(cd "$(dirname "$0")" 2>/dev/null && pwd || true)
mkdir -p "$BIN_DIR"

if [ -n "$here" ] && [ -f "$here/agent-fork" ] && [ -f "$here/skills/agent-fork/SKILL.md" ]; then
  # From a clone: link, so `git pull` updates everything.
  ln -sfn "$here/agent-fork" "$BIN_DIR/agent-fork"
  mkdir -p "$HOME/.agents/skills"
  if [ ! -e "$SKILL_HOME" ] || [ -L "$SKILL_HOME" ]; then
    ln -sfn "$here/skills/agent-fork" "$SKILL_HOME"
  fi
else
  curl -fsSL "$REPO_RAW/agent-fork" -o "$BIN_DIR/agent-fork"
  mkdir -p "$SKILL_HOME"
  curl -fsSL "$REPO_RAW/skills/agent-fork/SKILL.md" -o "$SKILL_HOME/SKILL.md"
fi
chmod +x "$BIN_DIR/agent-fork" 2>/dev/null || true

for dir in "$HOME/.claude/skills" "$HOME/.codex/skills" "${XDG_CONFIG_HOME:-$HOME/.config}/opencode/skills"; do
  parent=$(dirname "$dir")
  [ -d "$parent" ] || continue  # agent not installed
  mkdir -p "$dir"
  if [ ! -e "$dir/agent-fork" ] || [ -L "$dir/agent-fork" ]; then
    ln -sfn "$SKILL_HOME" "$dir/agent-fork"
    echo "skill  -> $dir/agent-fork"
  fi
done

echo "command -> $BIN_DIR/agent-fork"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "Add $BIN_DIR to your PATH to run agent-fork." ;;
esac
