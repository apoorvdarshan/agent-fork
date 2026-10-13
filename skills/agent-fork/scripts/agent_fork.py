#!/usr/bin/env python3
"""agent-fork - continue an AI coding chat in another coding agent.

Run by the `agent-fork` skill. Between Claude Code, Codex and OpenCode it copies
the chat into the target agent's own session format, so it shows up as real
history. Any other agent gets the chat as the first message of a new session
(a "handoff"). The new chat opens in a new terminal tab in the same folder.
"""

import argparse
import datetime
import glob
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

VERSION = "0.2.0"


def _agent(id, name, bins, prompt, aliases=(), packages=()):
    """bins: executables (first one found is launched; all count for detection).
    prompt: arguments that start an interactive session with a first message
    ("{prompt}" is replaced), or None if the CLI can't do that."""
    return {"id": id, "name": name, "bins": bins, "prompt": prompt,
            "aliases": aliases, "packages": packages}


AGENTS = [
    _agent("claude", "Claude Code", ("claude",), ["{prompt}"], ("cc", "claude-code", "claudecode")),
    _agent("codex", "Codex", ("codex",), ["{prompt}"], ("cx", "openai")),
    _agent("opencode", "OpenCode", ("opencode",), ["--prompt", "{prompt}"], ("oc", "open-code")),
    _agent("copilot", "GitHub Copilot", ("copilot",), ["-i", "{prompt}"], ("github", "gh-copilot"), ("@github/copilot",)),
    _agent("cursor", "Cursor", ("cursor-agent", "agent"), ["{prompt}"], ("cursor-agent",)),
    _agent("gemini", "Gemini CLI", ("gemini",), ["-i", "{prompt}"], ("gemini-cli",), ("@google/gemini-cli",)),
    _agent("qwen", "Qwen Code", ("qwen",), ["-i", "{prompt}"], ("qwen-code",), ("@qwen-code/",)),
    _agent("droid", "Factory Droid", ("droid",), ["{prompt}"], ("factory",)),
    _agent("kiro", "Kiro", ("kiro-cli",), ["chat", "{prompt}"], ("kiro-cli",)),
    _agent("cline", "Cline", ("cline",), ["{prompt}"]),
    _agent("kilo", "Kilo Code", ("kilo", "kilocode"), ["--prompt", "{prompt}"], ("kilocode", "kilo-code"), ("@kilocode/cli",)),
    _agent("pi", "Pi", ("pi",), ["{prompt}"], (), ("pi-coding-agent",)),
    _agent("auggie", "Auggie", ("auggie",), ["{prompt}"], ("augment",), ("@augmentcode/auggie",)),
    _agent("amp", "Amp", ("amp",), None, (), ("@sourcegraph/amp",)),
    _agent("goose", "Goose", ("goose",), ["run", "--interactive", "--text", "{prompt}"]),
    _agent("kimi", "Kimi Code", ("kimi",), None, ("kimi-code",)),
    _agent("vibe", "Mistral Vibe", ("vibe",), ["{prompt}"], ("mistral",)),
    _agent("junie", "Junie", ("junie",), None),
    _agent("qoder", "Qoder", ("qodercli", "qoder"), None, ("qodercli",)),
    _agent("openhands", "OpenHands", ("openhands",), ["-t", "{prompt}"]),
    _agent("crush", "Crush", ("crush",), None),
    _agent("devin", "Devin", ("devin",), ["--", "{prompt}"]),
    _agent("hermes", "Hermes", ("hermes",), ["chat", "-q", "{prompt}"]),
    _agent("openclaw", "OpenClaw", ("openclaw",), ["tui", "--message", "{prompt}"]),
    _agent("antigravity", "Antigravity", ("agy",), None, ("agy",)),
]
AGENT = {a["id"]: a for a in AGENTS}
NATIVE = ("claude", "codex", "opencode")  # read and written in their own session format
LABELS = dict((a["id"], a["name"]) for a in AGENTS)
LABELS["unknown"] = "another agent"
ALIASES = {}
for _a in AGENTS:
    for _name in (_a["id"],) + tuple(_a["aliases"]) + tuple(_a["bins"]):
        ALIASES.setdefault(_name, _a["id"])

SESSION_ENV = {
    "claude": "CLAUDE_CODE_SESSION_ID",
    "codex": "CODEX_THREAD_ID",
    "opencode": "OPENCODE_SESSION_ID",
}

CLAUDE_DIR = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
CODEX_HOME = os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")

# How much of each tool call to carry over. Tool output is history only; the
# new agent never re-runs it, so long output is trimmed to keep context small.
TOOL_LIMITS = {"short": (400, 800), "full": (None, None)}


class ForkError(Exception):
    pass


# ---------------------------------------------------------------- helpers


def now_ms():
    return int(time.time() * 1000)


def iso(ms=None):
    dt = datetime.datetime.fromtimestamp((ms or now_ms()) / 1000.0, tz=datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_ts(value):
    """Best-effort timestamp (ISO string, seconds or ms) -> epoch ms."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value if value > 1e12 else value * 1000)
    try:
        return int(datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def uuid7():
    raw = bytearray(now_ms().to_bytes(6, "big") + secrets.token_bytes(10))
    raw[6] = (raw[6] & 0x0F) | 0x70
    raw[8] = (raw[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(raw)))


_B62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_oc_clock = [0, 0]


def opencode_id(prefix, descending=False, ts=None):
    """Same shape as OpenCode's own ids: prefix_<12 hex time><14 base62>."""
    ts = ts if ts is not None else now_ms()
    if ts != _oc_clock[0]:
        _oc_clock[0], _oc_clock[1] = ts, 0
    _oc_clock[1] += 1
    value = ts * 0x1000 + _oc_clock[1]
    if descending:
        value = ~value
    value &= (1 << 48) - 1
    return "%s_%012x%s" % (prefix, value, "".join(secrets.choice(_B62) for _ in range(14)))


def trim(text, limit):
    text = (text or "").strip()
    if limit is None or len(text) <= limit:
        return text
    head = int(limit * 0.7)
    tail = limit - head
    return "%s\n… [%d chars trimmed] …\n%s" % (text[:head], len(text) - limit, text[-tail:])


def compact_json(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return value
    if isinstance(value, dict):
        for key in ("command", "cmd"):
            if isinstance(value.get(key), str) and len(value) <= 3:
                return value[key]
    return json.dumps(value, ensure_ascii=False)


def run(cmd, cwd=None, timeout=60):
    try:
        res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise ForkError("%s is not installed (or not on PATH)" % cmd[0])
    except subprocess.TimeoutExpired:
        raise ForkError("%s timed out" % " ".join(cmd[:3]))
    return res


def tool_version(binary, fallback):
    try:
        out = run([binary, "--version"], timeout=15).stdout
    except ForkError:
        return fallback
    m = re.search(r"\d+\.\d+\.\d+", out or "")
    return m.group(0) if m else fallback


FORK_CMD_RE = re.compile(r"agent_fork\.py|(^|[;&|])\s*agent-fork(\s|$)")
SHELL_TOOLS = ("bash", "shell", "exec_command", "exec", "local_shell", "run_shell_command")


def is_fork_command(cmd):
    """True for the `agent-fork ...` call that started this fork (left out of the copy)."""
    cmd = (cmd or "").strip()
    return bool(cmd) and bool(FORK_CMD_RE.search(cmd.splitlines()[0]))


# ---------------------------------------------------------------- transcript
#
# Every reader produces the same neutral transcript:
#   {"cwd", "title", "model", "turns": [{"user": str|None, "ts": ms|None,
#                                         "items": [{"kind": "text", "text"}
#                                                   | {"kind": "tool", "name", "input", "output"}]}]}


class Transcript(object):
    def __init__(self):
        self.cwd = None
        self.title = None
        self.model = None
        self.turns = []

    def _current(self):
        if not self.turns:
            self.turns.append({"user": None, "ts": None, "items": []})
        return self.turns[-1]

    def user(self, text, ts=None):
        text = (text or "").strip()
        if not text:
            return
        cur = self.turns[-1] if self.turns else None
        if cur is not None and not cur["items"] and cur["user"]:
            cur["user"] += "\n\n" + text  # consecutive user messages -> one turn
            return
        self.turns.append({"user": text, "ts": ts, "items": []})

    def text(self, text):
        text = (text or "").strip()
        if text:
            self._current()["items"].append({"kind": "text", "text": text})

    def tool(self, name, inp, output=None):
        item = {"kind": "tool", "name": name or "tool", "input": inp or "", "output": output or ""}
        if (name or "").lower() in SHELL_TOOLS and is_fork_command(inp):
            # The agent running `agent-fork` itself: that request is not part of the copy.
            self._current()["fork_request"] = True
            return item
        self._current()["items"].append(item)
        return item

    def finish(self):
        """Leave out the final "fork this chat" request that started this run."""
        last = self.turns[-1] if self.turns else None
        if last and re.search(r"fork", last["user"] or "", re.I):
            mentions = any("agent-fork" in (it.get("text") or "") for it in last["items"])
            if last.get("fork_request") or mentions:
                self.turns.pop()
        return self

    def message_count(self):
        return sum((1 if t["user"] else 0) + len(t["items"]) for t in self.turns)


def base_title(title):
    """Drop earlier "(from X)" / "(fork)" tags so repeated forks don't stack them."""
    title = (title or "").strip()
    while True:
        stripped = re.sub(r"\s*\((from (Claude Code|Codex|OpenCode)|fork)\)\s*$", "", title)
        if stripped == title:
            return title or "Forked chat"
        title = stripped


def render_items(turn, source, tools_mode):
    """Assistant-side items of a turn -> list of plain text blocks.

    Runs of tool calls collapse into one block, marked as history so the new
    agent treats them as context rather than requests to run again.
    """
    blocks, calls = [], []
    in_lim, out_lim = TOOL_LIMITS.get(tools_mode, TOOL_LIMITS["short"])

    def flush():
        if calls:
            blocks.append("[Earlier %s tool calls - already ran, shown as history]\n%s"
                          % (LABELS[source], "\n".join(calls)))
            del calls[:]

    for it in turn["items"]:
        if it["kind"] == "text":
            flush()
            blocks.append(it["text"])
        elif tools_mode != "none":
            line = "- %s: %s" % (it["name"], trim(it["input"], in_lim))
            if it["output"]:
                line += "\n  -> " + trim(it["output"], out_lim).replace("\n", "\n     ")
            calls.append(line)
    flush()
    return blocks


# ---------------------------------------------------------------- Claude Code


def claude_slug(cwd):
    return re.sub(r"[^A-Za-z0-9]", "-", cwd)


def claude_project_dir(cwd):
    base = os.path.join(CLAUDE_DIR, "projects")
    slug = claude_slug(cwd)
    direct = os.path.join(base, slug)
    if os.path.isdir(direct) or len(slug) <= 200:
        return direct
    # Claude shortens very long folder names; find the folder already used for cwd.
    for d in glob.glob(os.path.join(base, slug[:200] + "*")):
        for f in glob.glob(os.path.join(d, "*.jsonl"))[:3]:
            if _claude_file_cwd(f) == cwd:
                return d
    return direct


def _claude_file_cwd(path):
    try:
        with open(path) as fh:
            for i, line in enumerate(fh):
                if i > 50:
                    break
                if '"cwd"' in line:
                    return json.loads(line).get("cwd")
    except (OSError, ValueError):
        pass
    return None


def claude_find_file(sid):
    hits = glob.glob(os.path.join(CLAUDE_DIR, "projects", "*", sid + ".jsonl"))
    if not hits:
        raise ForkError("Claude Code session %s not found under %s/projects" % (sid, CLAUDE_DIR))
    return max(hits, key=os.path.getmtime)


def claude_sessions(cwd):
    d = claude_project_dir(cwd)
    out = []
    for f in glob.glob(os.path.join(d, "*.jsonl")):
        name = os.path.basename(f)[:-6]
        if re.match(r"^[0-9a-f-]{36}$", name):
            out.append((os.path.getmtime(f), name, f))
    out.sort(reverse=True)
    return [{"id": n, "updated": m, "title": None, "path": f} for m, n, f in out]


TAG_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)


def _tag(text, name):
    m = re.search(r"<%s>(.*?)</%s>" % (name, name), text, re.S)
    return m.group(1) if m else None


def read_claude(sid):
    path = claude_find_file(sid)
    entries = []
    with open(path) as fh:
        for line in fh:
            try:
                entries.append(json.loads(line))
            except ValueError:
                continue
    tr = Transcript()
    by_uuid = {}
    leaf = None
    for e in entries:
        if e.get("uuid"):
            by_uuid[e["uuid"]] = e
        if e.get("type") in ("user", "assistant") and not e.get("isSidechain"):
            leaf = e
        if e.get("type") in ("custom-title",) and e.get("customTitle"):
            tr.title = e["customTitle"]
        elif e.get("type") in ("ai-title",) and e.get("aiTitle") and not tr.title:
            tr.title = e["aiTitle"]
        elif e.get("type") == "summary" and e.get("summary") and not tr.title:
            tr.title = e["summary"]
        if e.get("cwd") and not tr.cwd:
            tr.cwd = e["cwd"]

    # Walk the active branch back from the newest message (skips rewound branches,
    # continues through /compact boundaries so earlier history is kept).
    chain, seen, e = [], set(), leaf
    while e is not None and e.get("uuid") not in seen:
        seen.add(e.get("uuid"))
        chain.append(e)
        e = by_uuid.get(e.get("parentUuid") or e.get("logicalParentUuid"))
    chain.reverse()

    pending = {}
    skip_output = False
    for e in chain:
        att = e.get("attachment") or {}
        if e.get("type") == "attachment" and att.get("type") == "queued_command" \
                and att.get("commandMode", "prompt") == "prompt" and isinstance(att.get("prompt"), str):
            tr.user(att["prompt"], parse_ts(e.get("timestamp")))  # sent while the agent was working
            continue
        if e.get("type") not in ("user", "assistant") or e.get("isSidechain") or e.get("isMeta"):
            continue
        msg = e.get("message") or {}
        content = msg.get("content")
        ts = parse_ts(e.get("timestamp"))
        if e["type"] == "assistant":
            if msg.get("model") and msg["model"] != "<synthetic>":
                tr.model = msg["model"]
            for b in content if isinstance(content, list) else [{"type": "text", "text": content}]:
                if b.get("type") == "text":
                    tr.text(b.get("text"))
                elif b.get("type") == "tool_use":
                    pending[b.get("id")] = tr.tool(b.get("name"), compact_json(b.get("input")))
            continue
        if e.get("isCompactSummary") and len(tr.turns) > 0:
            continue
        blocks = content if isinstance(content, list) else [{"type": "text", "text": content or ""}]
        texts = []
        for b in blocks:
            kind = b.get("type")
            if kind == "tool_result":
                out = b.get("content")
                if isinstance(out, list):
                    out = "\n".join(x.get("text", "[%s]" % x.get("type")) for x in out if isinstance(x, dict))
                item = pending.get(b.get("tool_use_id"))
                if item is not None:
                    item["output"] = ("[error] " if b.get("is_error") else "") + (out or "")
            elif kind == "image":
                texts.append("[image]")
            elif kind == "text":
                t = TAG_RE.sub("", b.get("text") or "").strip()
                command = _tag(t, "command-name")
                if command and command.strip().lstrip("/") == "agent-fork":
                    texts.append("%s %s" % (command.strip(), (_tag(t, "command-args") or "").strip()))
                    continue
                if not t or t.startswith(("<local-command-", "<command-name>", "<command-message>")):
                    continue
                bash_in = _tag(t, "bash-input")
                if bash_in is not None:
                    skip_output = is_fork_command(bash_in)
                    if not skip_output:
                        texts.append("$ " + bash_in.strip())
                    continue
                if "<bash-stdout>" in t or "<bash-stderr>" in t:
                    if not skip_output:
                        out = ((_tag(t, "bash-stdout") or "") + "\n" + (_tag(t, "bash-stderr") or "")).strip()
                        if out:
                            texts.append(trim(out, 1200))
                    skip_output = False
                    continue
                texts.append(t)
        if texts:
            tr.user("\n\n".join(texts), ts)
    return tr


def write_claude(tr, cwd, title, source):
    sid = str(uuid.uuid4())
    d = claude_project_dir(cwd)
    os.makedirs(d, exist_ok=True)
    version = tool_version("claude", "2.1.0")
    lines, parent = [], None
    base_ts = now_ms() - 1000 * (len(tr.turns) * 2 + 1)
    for i, turn in enumerate(tr.turns):
        common = {"isSidechain": False, "userType": "external", "cwd": cwd, "sessionId": sid,
                  "version": version, "gitBranch": ""}
        if turn["user"]:
            u = str(uuid.uuid4())
            lines.append(dict(common, parentUuid=parent, type="user", uuid=u, timestamp=iso(base_ts + 2000 * i),
                              message={"role": "user", "content": turn["user"]}))
            parent = u
        blocks = render_items(turn, source, ARGS.tools)
        if blocks:
            u = str(uuid.uuid4())
            lines.append(dict(common, parentUuid=parent, type="assistant", uuid=u,
                              timestamp=iso(base_ts + 2000 * i + 1000),
                              message={"id": "msg_fork_" + u.replace("-", "")[:20], "type": "message",
                                       "role": "assistant", "model": "<synthetic>",
                                       "content": [{"type": "text", "text": b} for b in blocks],
                                       "stop_reason": "end_turn", "stop_sequence": None,
                                       "usage": {"input_tokens": 0, "output_tokens": 0}}))
            parent = u
    lines.append({"type": "custom-title", "customTitle": title, "sessionId": sid})
    with open(os.path.join(d, sid + ".jsonl"), "w") as fh:
        for line in lines:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    return sid, "claude --resume %s" % sid


# ---------------------------------------------------------------- Codex


class CodexServer(object):
    """Minimal JSON-RPC client for `codex app-server` (stdio), used read-only."""

    def __init__(self):
        binary = shutil.which("codex")
        if not binary:
            raise ForkError("codex is not installed (or not on PATH)")
        self.proc = subprocess.Popen([binary, "app-server", "-c", "mcp_servers={}"],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self.next_id = 0
        self.call("initialize", {"clientInfo": {"name": "agent-fork", "version": VERSION},
                                 "capabilities": {"experimentalApi": True}})
        self._send({"method": "initialized"})

    def _send(self, msg):
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def call(self, method, params, timeout=60):
        self.next_id += 1
        rid = self.next_id
        self._send({"id": rid, "method": method, "params": params})
        deadline = time.time() + timeout
        while time.time() < deadline:
            line = self.proc.stdout.readline()
            if not line:
                raise ForkError("codex app-server exited unexpectedly")
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if msg.get("id") == rid and ("result" in msg or "error" in msg):
                if "error" in msg:
                    raise ForkError("codex %s failed: %s" % (method, msg["error"].get("message", msg["error"])))
                return msg["result"]
        raise ForkError("codex %s timed out" % method)

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


def _codex_cmd(command):
    m = re.match(r"^\S*(?:zsh|bash|sh) -l?c (.*)$", command or "", re.S)
    if m:
        try:
            parts = shlex.split(m.group(1))
            if len(parts) == 1:
                return parts[0]
        except ValueError:
            pass
    return command or ""


def _text_of(content):
    out = []
    for c in content or []:
        if not isinstance(c, dict):
            continue
        if c.get("text"):
            out.append(c["text"])
        elif c.get("type") in ("image", "localImage", "input_image"):
            out.append("[image]")
    return "\n".join(out)


def read_codex(tid):
    srv = CodexServer()
    try:
        meta = srv.call("thread/read", {"threadId": tid}).get("thread", {})
        items, cursor = [], None
        if meta.get("historyMode") == "paginated":
            while True:
                res = srv.call("thread/items/list", {"threadId": tid, "limit": 500, "cursor": cursor})
                items.extend(res.get("data", []))
                cursor = res.get("nextCursor")
                if not cursor:
                    break
        else:  # older (legacy) threads only support full reads
            full = srv.call("thread/read", {"threadId": tid, "includeTurns": True}).get("thread", {})
            for turn in full.get("turns") or []:
                for it in turn.get("items") or []:
                    items.append({"turnId": turn.get("id"), "item": it})
    finally:
        srv.close()
    tr = Transcript()
    tr.cwd = meta.get("cwd")
    preview = (meta.get("preview") or "").strip()
    tr.title = meta.get("name") or (preview.splitlines()[0][:80] if preview else None)
    tr.model = meta.get("model")
    for entry in items:
        it = entry.get("item") or {}
        kind = it.get("type")
        if kind == "userMessage":
            tr.user(_text_of(it.get("content")), entry.get("startedAtMs"))
        elif kind == "agentMessage":
            tr.text(it.get("text"))
        elif kind == "commandExecution":
            cmd = _codex_cmd(it.get("command"))
            out = it.get("aggregatedOutput") or ""
            if it.get("exitCode") not in (None, 0):
                out = "%s\n[exit code %s]" % (out, it.get("exitCode"))
            tr.tool("shell", cmd, out)
        elif kind == "fileChange":
            changes = it.get("changes") or []
            summary = "\n".join("%s %s" % ((c.get("kind") or {}).get("type", "edit"), c.get("path")) for c in changes)
            diffs = "\n".join(c.get("diff") or "" for c in changes)
            tr.tool("apply_patch", summary, diffs)
        elif kind == "mcpToolCall":
            res = it.get("result") or {}
            out = _text_of(res.get("content")) if isinstance(res, dict) else str(res)
            if it.get("error"):
                out = "[error] %s" % (it["error"].get("message") if isinstance(it["error"], dict) else it["error"])
            tr.tool("%s.%s" % (it.get("server"), it.get("tool")), compact_json(it.get("arguments")), out)
        elif kind == "dynamicToolCall":
            tr.tool(it.get("tool"), compact_json(it.get("arguments")), _text_of(it.get("contentItems")))
        elif kind == "webSearch":
            action = it.get("action") or {}
            q = it.get("query") or ", ".join(action.get("queries") or []) or action.get("url") or ""
            tr.tool("web_search", q, "")
    return tr


def codex_thread_cwd(tid):
    srv = CodexServer()
    try:
        cwd = srv.call("thread/read", {"threadId": tid}).get("thread", {}).get("cwd")
    finally:
        srv.close()
    return cwd if cwd and os.path.isdir(cwd) else None


def codex_sessions(cwd, limit=8):
    files = glob.glob(os.path.join(CODEX_HOME, "sessions", "*", "*", "*", "rollout-*.jsonl"))
    files.sort(key=os.path.getmtime, reverse=True)
    out, seen = [], set()
    for f in files[:400]:
        try:
            with open(f) as fh:
                first = json.loads(fh.readline())
        except (OSError, ValueError):
            continue
        p = first.get("payload") or {}
        if first.get("type") != "session_meta" or p.get("cwd") != cwd or p.get("id") in seen:
            continue
        if p.get("thread_source") == "subagent" or p.get("source") in ("exec", "mcp"):
            continue
        seen.add(p.get("id"))
        out.append({"id": p.get("id"), "updated": os.path.getmtime(f), "title": None, "path": f})
        if len(out) >= limit:
            break
    return out


def write_codex(tr, cwd, title, source):
    tid = uuid7()
    local = datetime.datetime.now()
    d = os.path.join(CODEX_HOME, "sessions", local.strftime("%Y"), local.strftime("%m"), local.strftime("%d"))
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "rollout-%s-%s.jsonl" % (local.strftime("%Y-%m-%dT%H-%M-%S"), tid))
    stamp = iso()
    lines = [{"timestamp": stamp, "type": "session_meta", "payload": {
        "session_id": tid, "id": tid, "timestamp": stamp, "cwd": cwd, "originator": "agent_fork",
        "cli_version": tool_version("codex", "0.0.0"), "source": "cli", "model_provider": "openai",
        "history_mode": "legacy"}}]
    started = int(time.time())
    for i, turn in enumerate(tr.turns, 1):
        turn_id = "agent-fork-turn-%d" % i
        events = [("event_msg", {"type": "task_started", "turn_id": turn_id, "started_at": started,
                                 "model_context_window": None, "collaboration_mode_kind": "default"})]
        if turn["user"]:
            events += [
                ("event_msg", {"type": "user_message", "message": turn["user"], "local_images": [],
                               "local_audio": [], "text_elements": []}),
                ("response_item", {"type": "message", "role": "user",
                                   "content": [{"type": "input_text", "text": turn["user"]}]}),
            ]
        for block in render_items(turn, source, ARGS.tools):
            events += [
                ("event_msg", {"type": "agent_message", "message": block, "phase": None, "memory_citation": None}),
                ("response_item", {"type": "message", "role": "assistant",
                                   "content": [{"type": "output_text", "text": block}]}),
            ]
        events.append(("event_msg", {"type": "task_complete", "turn_id": turn_id,
                                     "last_agent_message": None, "started_at": started}))
        lines += [{"timestamp": stamp, "type": t, "payload": p} for t, p in events]
    with open(path, "w") as fh:
        for line in lines:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    try:  # lets `codex resume` show a readable name
        with open(os.path.join(CODEX_HOME, "session_index.jsonl"), "a") as fh:
            fh.write(json.dumps({"id": tid, "thread_name": title,
                                 "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")}) + "\n")
    except OSError:
        pass
    return tid, "codex resume %s" % tid


# ---------------------------------------------------------------- OpenCode


def opencode_export(sid):
    # Export into a file: large exports get cut off when read through a pipe.
    with tempfile.TemporaryFile(mode="w+") as out:
        try:
            res = subprocess.run(["opencode", "session", "export", sid], stdout=out,
                                 stderr=subprocess.PIPE, text=True, timeout=120)
        except FileNotFoundError:
            raise ForkError("opencode is not installed (or not on PATH)")
        except subprocess.TimeoutExpired:
            raise ForkError("opencode export timed out")
        out.seek(0)
        body = out.read()
    if res.returncode != 0 or not body.strip():
        raise ForkError("opencode could not export session %s: %s" % (sid, (res.stderr or "").strip()[-300:]))
    try:
        return json.loads(body)
    except ValueError:
        raise ForkError("opencode export returned invalid JSON")


def read_opencode(sid):
    data = opencode_export(sid)
    info = data.get("info") or {}
    tr = Transcript()
    tr.cwd = (info.get("location") or {}).get("directory")
    tr.title = info.get("title")
    model = info.get("model") or {}
    tr.model = model.get("id") if isinstance(model, dict) else model
    for m in data.get("messages", []):
        kind = m.get("type")
        ts = (m.get("time") or {}).get("created")
        if kind == "user":
            text = m.get("text") or ""
            files = [f.get("filename") or f.get("url") or "file" for f in m.get("files") or [] if isinstance(f, dict)]
            if files:
                text += "\n[attached: %s]" % ", ".join(files)
            tr.user(text, ts)
        elif kind == "assistant":
            for part in m.get("content") or []:
                ptype = part.get("type")
                if ptype == "text":
                    tr.text(part.get("text"))
                elif ptype in ("reasoning", "step-start", "step-finish", "snapshot", "patch"):
                    continue
                elif part.get("tool") or part.get("name") or ptype in ("tool", "tool-call"):
                    state = part.get("state") or {}
                    inp = part.get("input", state.get("input"))
                    out = part.get("output", state.get("output") or state.get("error") or "")
                    if isinstance(out, (dict, list)):
                        out = json.dumps(out, ensure_ascii=False)
                    tr.tool(part.get("tool") or part.get("name") or ptype, compact_json(inp), out)
        elif kind == "shell":
            cmd = m.get("command") or m.get("text") or ""
            if not is_fork_command(cmd):
                tr.user("$ %s\n%s" % (cmd, trim(m.get("output") or "", 1200)), ts)
    return tr


def opencode_sessions(cwd):
    res = run(["opencode", "session", "list", "--format", "json", "-n", "50"], cwd=cwd, timeout=60)
    try:
        rows = json.loads(res.stdout or "[]")
    except ValueError:
        return []
    rows = [r for r in rows if r.get("directory") == cwd]
    rows.sort(key=lambda r: r.get("updated") or 0, reverse=True)
    return [{"id": r["id"], "updated": (r.get("updated") or 0) / 1000.0, "title": r.get("title")} for r in rows]


def opencode_import(data, cwd):
    fd, tmp = tempfile.mkstemp(prefix="agent-fork-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, ensure_ascii=False)
        res = run(["opencode", "session", "import", tmp, "--directory", cwd], cwd=cwd, timeout=120)
    finally:
        os.unlink(tmp)
    m = re.search(r"(ses_[A-Za-z0-9]+)", res.stdout or "")
    if res.returncode != 0 or not m:
        raise ForkError("opencode import failed: %s" % ((res.stderr or res.stdout or "").strip()[-400:]))
    return m.group(1)


def _oc_info(sid, title, cwd, ts):
    return {"id": sid, "projectID": "global", "title": title, "location": {"directory": cwd},
            "cost": 0, "tokens": {"input": 0, "output": 0, "reasoning": 0, "cache": {"read": 0, "write": 0}},
            "time": {"created": ts, "updated": ts}}


def write_opencode(tr, cwd, title, source):
    start = now_ms() - 1000 * (len(tr.turns) * 2 + 1)
    messages = []
    for i, turn in enumerate(tr.turns):
        t = start + 2000 * i
        if turn["user"]:
            messages.append({"id": opencode_id("msg", ts=t), "type": "user", "time": {"created": t},
                             "text": turn["user"], "files": []})
        blocks = render_items(turn, source, ARGS.tools)
        if blocks:
            messages.append({"id": opencode_id("msg", ts=t + 1000), "type": "assistant",
                             "time": {"created": t + 1000, "completed": t + 1000},
                             "agent": "build",
                             "model": {"id": tr.model or "history", "providerID": source},
                             "content": [{"type": "text", "text": b} for b in blocks],
                             "finish": "stop"})
    sid = opencode_import({"info": _oc_info(opencode_id("ses", descending=True), title, cwd, now_ms()),
                           "messages": messages}, cwd)
    return sid, "opencode --session %s" % sid


def fork_opencode_native(sid, cwd=None):
    """OpenCode -> OpenCode: copy the exported session under fresh ids."""
    data = opencode_export(sid)
    info = data.get("info") or {}
    cwd = cwd or (info.get("location") or {}).get("directory") or os.getcwd()
    ts = now_ms()
    title = "%s (fork)" % base_title(info.get("title") or "OpenCode chat")
    new_info = dict(info, id=opencode_id("ses", descending=True), title=title)
    new_info["location"] = dict(info.get("location") or {}, directory=cwd)
    new_info["time"] = dict(info.get("time") or {}, created=ts, updated=ts)
    new_info.setdefault("projectID", "global")
    messages = []
    for m in data.get("messages", []):
        created = (m.get("time") or {}).get("created") or ts
        messages.append(dict(m, id=opencode_id("msg", ts=created)))
    new_id = opencode_import({"info": new_info, "messages": messages}, cwd)
    return cwd, new_id, "opencode --session %s" % new_id


# ---------------------------------------------------------------- detection

INTERPRETERS = ("node", "bun", "deno", "python", "python3", "bash", "sh", "zsh", "fish", "env")


def _process_agent(args):
    """Agent id for one process command line, if it is a known agent."""
    try:
        argv = shlex.split(args)
    except ValueError:
        argv = args.split()
    if not argv:
        return None
    paths = [argv[0]]
    if re.sub(r"[\d.]+$", "", os.path.basename(argv[0]).lower()) in INTERPRETERS:
        paths += [a for a in argv[1:3] if not a.startswith("-") and " " not in a]  # the script it runs
    names = [re.sub(r"\.(js|mjs|cjs|py|sh)$", "", os.path.basename(p).lower()) for p in paths]
    for a in AGENTS:
        if a["id"] == "cursor" and "cursor-agent" not in names and "cursor" not in paths[0].lower():
            continue  # a bare `agent` command only counts when it is Cursor's
        if any(n in a["bins"] for n in names) or any(pkg in p for pkg in a["packages"] for p in paths):
            return a["id"]
    return None


def ancestor_agent():
    """Which agent is this command running inside? The nearest one wins."""
    try:
        out = subprocess.run(["ps", "-axo", "pid=,ppid=,args="], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return None
    procs = {}
    for line in out.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            procs[int(parts[0])] = (int(parts[1]), parts[2])
    pid, hops = os.getppid(), 0
    while pid in procs and pid > 1 and hops < 40:
        ppid, args = procs[pid]
        found = _process_agent(args)
        if found:
            return found
        pid, hops = ppid, hops + 1
    return None


def list_sessions(tool, cwd):
    if tool == "claude":
        return claude_sessions(cwd)
    if tool == "codex":
        return codex_sessions(cwd)
    return opencode_sessions(cwd)


def resolve_source(cwd):
    """-> (agent id, session id). The session id is None when that agent's chats
    can't be read from disk, so the agent has to write a handoff instead."""
    agent = ARGS.source or ancestor_agent()
    if not agent:
        for t in ("codex", "opencode", "claude"):
            if os.environ.get(SESSION_ENV[t]):
                agent = t
                break
    if agent and agent not in NATIVE:
        return agent, None
    sid = ARGS.session or (os.environ.get(SESSION_ENV[agent]) if agent else None)
    if agent and sid:
        return agent, sid
    if not agent and ARGS.via_skill:
        return "unknown", None  # run by an agent we don't recognise
    # Run from a plain terminal: take the most recently active chat in this folder.
    best = None
    for t in ([agent] if agent else NATIVE):
        try:
            rows = list_sessions(t, cwd)
        except ForkError:
            continue
        if rows and (best is None or rows[0]["updated"] > best[2]):
            best = (t, rows[0]["id"], rows[0]["updated"])
    if not best:
        raise ForkError("no chat found to fork in %s (use --from and --session)" % cwd)
    say("Using latest %s chat in this folder: %s" % (LABELS[best[0]], best[1]))
    return best[0], best[1]


# ---------------------------------------------------------------- handoff

HANDOFF_FILE = ".agent-fork-handoff.md"
MAX_PROMPT_CHARS = 300000  # stays well under the OS argument limit


def need_handoff(source, target, cwd):
    path = os.path.join(cwd, HANDOFF_FILE)
    script = os.path.abspath(sys.argv[0])
    print("NEED_HANDOFF")
    print("%s chats can't be read from disk, so write the handoff yourself:" % LABELS[source])
    print("1. Write the whole conversation so far, as Markdown, to: %s" % path)
    print("   Include every user request in order (quoted closely), what you did and found")
    print("   (files read or changed, commands and key results), decisions, the current")
    print("   state, and what is unfinished or next. Be specific; don't invent anything.")
    print("2. Then run: python3 %s %s --from %s --handoff %s"
          % (shlex.quote(script), target, source, shlex.quote(path)))
    return 3


def read_handoff(path):
    if path == "-":
        return sys.stdin.read()
    try:
        with open(path) as fh:
            text = fh.read()
    except OSError as e:
        raise ForkError("can't read handoff file %s: %s" % (path, e.strerror))
    if os.path.basename(path) == HANDOFF_FILE:
        try:
            os.unlink(path)  # temporary file in the project folder; a copy is kept in the cache
        except OSError:
            pass
    if not text.strip():
        raise ForkError("the handoff file %s is empty" % path)
    return text


def transcript_parts(tr, source):
    parts = []
    for turn in tr.turns:
        if turn["user"]:
            parts.append("## User\n\n" + turn["user"])
        blocks = render_items(turn, source, ARGS.tools)
        if blocks:
            parts.append("## Assistant\n\n" + "\n\n".join(blocks))
    return parts


def handoff_prompt(source, parts):
    body = "\n\n".join(parts)
    if len(body) > MAX_PROMPT_CHARS:  # keep the newest messages
        kept, size = [], 0
        for part in reversed(parts):
            if size + len(part) + 2 > MAX_PROMPT_CHARS:
                break
            kept.insert(0, part)
            size += len(part) + 2
        body = "[Earlier messages omitted to fit]\n\n" + ("\n\n".join(kept) if kept else parts[-1][-MAX_PROMPT_CHARS:])
    return ("Continue this conversation. It was moved here from %s with agent-fork. Everything "
            "inside <previous-conversation> already happened: use it as context, and don't redo "
            "finished work or re-run its commands. Reply with one short line saying you're ready, "
            "then wait for my next message.\n\n<previous-conversation>\n%s\n</previous-conversation>\n"
            % (LABELS[source], body))


def save_prompt(prompt, source, target):
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    d = os.path.join(base, "agent-fork")
    os.makedirs(d, exist_ok=True)
    for old in glob.glob(os.path.join(d, "handoff-*.md")):  # keep a week of handoffs
        try:
            if time.time() - os.path.getmtime(old) > 7 * 86400:
                os.unlink(old)
        except OSError:
            pass
    path = os.path.join(d, "handoff-%s-%s-to-%s.md" % (time.strftime("%Y%m%d-%H%M%S"), source, target))
    with open(path, "w") as fh:
        fh.write(prompt)
    return path


def find_binary(names):
    """First installed command from names; ignores terminal-provided wrapper shims."""
    dirs = [d for d in os.environ.get("PATH", "").split(os.pathsep) if d and "cmux-cli-shims" not in d]
    for name in names:
        for d in dirs:
            p = os.path.join(d, name)
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return name
    return None


def launch_command(target, prompt_path):
    """-> (shell command, True if it passes the chat as the first message)."""
    a = AGENT[target]
    binary = find_binary(a["bins"])
    if not binary:
        raise ForkError("%s isn't installed (no `%s` command found)" % (a["name"], a["bins"][0]))
    if a["prompt"] is None:
        return shlex.quote(binary), False
    words = [shlex.quote(binary)]
    for w in a["prompt"]:
        words.append('"$(cat %s)"' % shlex.quote(prompt_path) if w == "{prompt}" else shlex.quote(w))
    return " ".join(words), True


def copy_to_clipboard(text):
    for cmd in (["pbcopy"], ["wl-copy"], ["xclip", "-selection", "clipboard"]):
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, input=text, text=True, timeout=10, check=True)
                return True
            except Exception:
                continue
    return False


# ---------------------------------------------------------------- opening


def open_tab(cwd, command, how, focus=True):
    if how == "print":
        return False
    shell_line = "cd %s && %s" % (shlex.quote(cwd), command)
    if shutil.which("cmux") and (os.environ.get("CMUX_SOCKET_PATH") or os.environ.get("CMUX_WORKSPACE_ID")):
        # cmux types the command into a fresh interactive shell, so the user's aliases apply.
        flag = ["--focus", "true" if focus else "false"]
        if how == "split":
            cmd = ["cmux", "new-split", "right", "--command", shell_line] + flag
        elif how == "workspace":
            cmd = ["cmux", "new-workspace", "--cwd", cwd, "--command", command] + flag
        else:
            cmd = ["cmux", "new-surface", "--working-directory", cwd, "--command", command] + flag
        env = dict(os.environ, CMUX_QUIET="1")
        return subprocess.run(cmd, capture_output=True, text=True, env=env).returncode == 0
    if os.environ.get("TMUX") and shutil.which("tmux"):
        detach = [] if focus else ["-d"]
        if how == "split":
            cmd = ["tmux", "split-window", "-h"] + detach + ["-c", cwd, command]
        else:
            cmd = ["tmux", "new-window"] + detach + ["-c", cwd, command]
        return subprocess.run(cmd, capture_output=True).returncode == 0
    term = os.environ.get("TERM_PROGRAM", "")
    if sys.platform == "darwin" and term == "iTerm.app":
        script = ('tell application "iTerm2" to tell current window\n'
                  'create tab with default profile\n'
                  'tell current session to write text %s\nend tell' % json.dumps(shell_line))
        return subprocess.run(["osascript", "-e", script], capture_output=True).returncode == 0
    if sys.platform == "darwin" and term == "Apple_Terminal":
        script = 'tell application "Terminal" to do script %s' % json.dumps(shell_line)
        return subprocess.run(["osascript", "-e", script], capture_output=True).returncode == 0
    return False


# ---------------------------------------------------------------- main

ARGS = None


def say(msg):
    if not ARGS or not ARGS.quiet:
        print(msg)


def cmd_list(cwd):
    print("Chats in %s" % cwd)
    for t in NATIVE:
        try:
            rows = list_sessions(t, cwd)[:5]
        except ForkError as e:
            print("  %-12s (%s)" % (LABELS[t], e))
            continue
        if not rows:
            print("  %-12s none" % LABELS[t])
            continue
        for i, r in enumerate(rows):
            when = datetime.datetime.fromtimestamp(r["updated"]).strftime("%b %d %H:%M")
            print("  %-12s %s  %s  %s" % (LABELS[t] if i == 0 else "", when, r["id"], r.get("title") or ""))


def main(argv=None):
    global ARGS
    p = argparse.ArgumentParser(
        prog="agent_fork.py",
        description="Continue the current AI coding chat in another agent, in a new terminal tab "
                    "in the same folder. Normally run by the agent-fork skill.",
        epilog="agents: " + ", ".join(a["id"] for a in AGENTS),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("target", nargs="?", help="agent to continue in (default: same agent)")
    p.add_argument("--from", dest="source", metavar="AGENT", help="source agent (auto-detected)")
    p.add_argument("--session", metavar="ID", help="source session id (auto-detected)")
    p.add_argument("--handoff", metavar="FILE", help="chat written by the agent itself ('-' for stdin)")
    p.add_argument("--cwd", metavar="DIR", help="folder to open in (default: the chat's folder)")
    p.add_argument("--split", dest="how", action="store_const", const="split", help="open in a split instead of a tab")
    p.add_argument("--workspace", dest="how", action="store_const", const="workspace", help="open in a new cmux workspace")
    p.add_argument("--no-open", dest="how", action="store_const", const="print", help="only create the fork and print the command")
    p.add_argument("--no-focus", dest="focus", action="store_false", help="open the new tab without switching to it")
    p.add_argument("--tools", choices=("short", "full", "none"), default="short",
                   help="how much tool-call history to carry over (default: short)")
    p.add_argument("--list", action="store_true", help="list recent Claude/Codex/OpenCode chats in this folder")
    p.add_argument("--via-skill", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("-q", "--quiet", action="store_true")
    p.add_argument("--version", action="version", version="agent-fork %s" % VERSION)
    p.set_defaults(how="tab")
    ARGS = p.parse_args(argv)

    for attr in ("target", "source"):
        val = getattr(ARGS, attr)
        if val:
            if val.lower() not in ALIASES:
                p.error("unknown agent %r (known: %s)" % (val, ", ".join(a["id"] for a in AGENTS)))
            setattr(ARGS, attr, ALIASES[val.lower()])

    here = os.path.realpath(ARGS.cwd) if ARGS.cwd else os.getcwd()
    count, new_id, prompt_path, auto = None, None, None, True
    try:
        if ARGS.list:
            cmd_list(here)
            return 0
        if ARGS.handoff:
            source = ARGS.source or ancestor_agent() or "unknown"
            target = ARGS.target or (source if source != "unknown" else None)
            parts = [read_handoff(ARGS.handoff)]
            cwd = here
        else:
            source, sid = resolve_source(here)
            target = ARGS.target or (source if source != "unknown" else None)
            if target is None:
                raise ForkError("say which agent to fork to (for example: codex)")
            if sid is None:
                return need_handoff(source, target, here)
            parts = None
            if source == target:  # same agent: use its own fork
                if source == "claude":
                    cwd = here if ARGS.cwd else (_claude_file_cwd(claude_find_file(sid)) or here)
                    command = "claude --resume %s --fork-session" % sid
                elif source == "codex":
                    cwd = here if ARGS.cwd else (codex_thread_cwd(sid) or here)
                    command = "codex fork %s" % sid
                else:
                    cwd, new_id, command = fork_opencode_native(sid, here if ARGS.cwd else None)
            else:
                reader = {"claude": read_claude, "codex": read_codex, "opencode": read_opencode}[source]
                tr = reader(sid).finish()
                if not tr.turns:
                    raise ForkError("the %s chat %s has no messages yet" % (LABELS[source], sid))
                cwd = here if ARGS.cwd else (tr.cwd if tr.cwd and os.path.isdir(tr.cwd) else here)
                count = tr.message_count()
                if target in NATIVE:  # real history in the target's own format
                    title = "%s (from %s)" % (base_title(tr.title)[:80], LABELS[source])
                    writer = {"claude": write_claude, "codex": write_codex, "opencode": write_opencode}[target]
                    new_id, command = writer(tr, cwd, title, source)
                else:
                    parts = transcript_parts(tr, source)
        if parts is not None:  # handoff: the chat becomes the new session's first message
            if target not in AGENT:
                raise ForkError("say which agent to fork to (for example: codex)")
            if not find_binary(AGENT[target]["bins"]):
                raise ForkError("%s isn't installed (no `%s` command found)"
                                % (LABELS[target], AGENT[target]["bins"][0]))
            prompt = handoff_prompt(source, parts)
            prompt_path = save_prompt(prompt, source, target)
            command, auto = launch_command(target, prompt_path)
            if not auto:
                auto = None if copy_to_clipboard(prompt) else False
    except ForkError as e:
        print("agent-fork: %s" % e, file=sys.stderr)
        return 1

    what = "%s chat%s" % (LABELS[source], " (%d messages)" % count if count else "")
    if prompt_path is None:
        say("Forked %s -> %s%s" % (what, LABELS[target], " " + new_id if new_id else ""))
    elif auto:
        say("Handed %s to %s as the first message of a new chat" % (what, LABELS[target]))
    else:
        say("Opening %s. It can't take a first message, so %s" % (
            LABELS[target], "the chat is on your clipboard: paste it (Cmd+V) and press Enter."
            if auto is None else "paste the chat from %s." % prompt_path))
    if open_tab(cwd, command, ARGS.how, ARGS.focus):
        say("Opened in a new %s." % ("split" if ARGS.how == "split" else "tab"))
    else:
        say("Run this to open it:\n  cd %s && %s" % (shlex.quote(cwd), command))
    return 0


if __name__ == "__main__":
    sys.exit(main())
