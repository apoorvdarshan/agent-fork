# agent-fork (moved to Sesslet)

agent-fork is now part of [Sesslet](https://github.com/apoorvdarshan/sesslet).
This repository is archived.

The skill lives at
[`sesslet/skills/agent-fork`](https://github.com/apoorvdarshan/sesslet/tree/main/skills/agent-fork).
It forks the chat you're in into another coding agent and opens it in a new
terminal tab in the same folder. In Claude Code type `/agent-fork codex`; in
other agents ask "fork this chat to opencode".

To install, clone Sesslet, then from its `bridge` folder run:

```sh
npm ci
npm run skill:install
```

See [Sesslet's README](https://github.com/apoorvdarshan/sesslet#fork-from-inside-an-agent)
for details. Sesslet's iPhone app uses the same converter for **Fork to…**.
