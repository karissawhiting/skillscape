"""skillscape: map the context and skills Claude Code sees from a repo.

Run from inside a repo. Scans CLAUDE.md files, memory, rules, skills,
commands and agents, then opens a self-contained HTML page.

Only reads files under ~/.claude/, the repo's .claude/, and CLAUDE*.md files
on the path from the repo root upward. Never walks the general repo tree.
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
import webbrowser
from datetime import datetime
from pathlib import Path

HOME = Path.home()
CLAUDE_DIR = HOME / ".claude"
TEMPLATE = Path(__file__).resolve().with_name("template.html")

# Directory names we refuse to read from (data folders).
DATA_DIR = re.compile(r"data", re.IGNORECASE)


# ---------------------------------------------------------------- helpers

def is_safe(path: Path) -> bool:
    """False if any directory in the path looks like a data folder or a volume."""
    p = path.expanduser().resolve()
    if str(p).startswith("/Volumes/"):
        return False
    return not any(DATA_DIR.search(part) for part in p.parent.parts)


def read_text(path: Path):
    if not is_safe(path) or not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def read_json(path: Path):
    text = read_text(path)
    if text is None:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def parse_frontmatter(text: str):
    """Tiny YAML-frontmatter parser: top-level `key: value` plus `>`/`|` blocks."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, re.DOTALL)
    if not m:
        return {}, text
    meta, key, block = {}, None, []
    for line in m.group(1).splitlines():
        kv = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if kv:
            if key and block:
                meta[key] = " ".join(block).strip()
            key, val = kv.group(1), kv.group(2).strip()
            block = []
            if val in (">", "|", ">-", "|-"):
                continue
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                val = val[1:-1]
            meta[key] = val
            key = key if val == "" else None
        elif key and line.startswith((" ", "\t")):
            block.append(line.strip())
    if key and block:
        meta[key] = " ".join(block).strip()
    return meta, text[m.end():]


def repo_root(cwd: Path) -> Path:
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd,
                             capture_output=True, text=True, check=True)
        return Path(out.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return cwd


def display(path: Path) -> str:
    s = str(path)
    return "~" + s[len(str(HOME)):] if s.startswith(str(HOME)) else s


# ---------------------------------------------------------------- context

def context_item(path: Path, kind: str, scope: str):
    text = read_text(path)
    if text is None:
        return None
    return {"id": display(path), "name": path.name, "kind": kind, "scope": scope,
            "path": display(path), "body": text}


def follow_imports(item, seen, out):
    """Add files pulled in via `@path` imports (one level deep)."""
    base = Path(item["path"].replace("~", str(HOME), 1)).parent
    for m in re.finditer(r"(?<![\w`])@([~./\w-][^\s`)]*)", item["body"]):
        ref = m.group(1)
        p = Path(ref).expanduser() if ref.startswith("~") else (base / ref)
        p = p.resolve()
        if p in seen or p.suffix.lower() not in (".md", ".txt", ""):
            continue
        it = context_item(p, "import", f"imported by {item['name']}")
        if it:
            seen.add(p)
            out.append(it)


def scan_context(root: Path):
    out, seen = [], set()

    def add(path, kind, scope):
        p = path.resolve() if path.exists() else path
        if p in seen:
            return
        it = context_item(path, kind, scope)
        if it:
            seen.add(p)
            out.append(it)

    add(CLAUDE_DIR / "CLAUDE.md", "instructions", "user")
    # Repo root and every ancestor directory.
    for d in [root, *root.parents]:
        scope = "project" if d == root else "ancestor"
        for name in ("CLAUDE.md", "CLAUDE.local.md"):
            add(d / name, "instructions", scope)
    add(root / ".claude" / "CLAUDE.md", "instructions", "project")

    for rules_dir, scope in ((CLAUDE_DIR / "rules", "user"),
                             (root / ".claude" / "rules", "project")):
        if rules_dir.is_dir():
            for f in sorted(rules_dir.rglob("*.md")):
                add(f, "rule", scope)

    for it in list(out):
        follow_imports(it, seen, out)

    slug = re.sub(r"[^A-Za-z0-9]", "-", str(root))
    mem_dir = CLAUDE_DIR / "projects" / slug / "memory"
    add(mem_dir / "MEMORY.md", "memory", "project")
    if mem_dir.is_dir():
        for f in sorted(mem_dir.glob("*.md")):
            add(f, "memory", "project")
    return out


# ---------------------------------------------------------------- skills etc.

def skill_item(skill_md: Path, scope: str, prefix: str = ""):
    text = read_text(skill_md)
    if text is None:
        return None
    meta, body = parse_frontmatter(text)
    name = meta.get("name") or skill_md.parent.name
    return {"id": display(skill_md), "name": name,
            "full_name": f"{prefix}:{name}" if prefix else name,
            "description": meta.get("description", ""), "kind": "skill",
            "scope": scope, "path": display(skill_md), "body": body}


def skills_in(skills_dir: Path, scope: str, prefix: str = ""):
    out = []
    if not skills_dir.is_dir():
        return out
    for d in sorted(skills_dir.iterdir()):
        if d.name == "synced":
            continue
        if not is_safe(d / "SKILL.md"):
            # Listed but deliberately not read: the folder name looks like data.
            out.append({"id": display(d), "name": d.name,
                        "full_name": f"{prefix}:{d.name}" if prefix else d.name,
                        "description": "(not read: folder name looks like a data folder)",
                        "kind": "skill", "scope": scope, "path": display(d), "body": ""})
            continue
        it = skill_item(d / "SKILL.md", scope, prefix)
        if it:
            out.append(it)
    return out


def enabled_plugins(root: Path):
    enabled = {}
    for f in (CLAUDE_DIR / "settings.json", root / ".claude" / "settings.json",
              root / ".claude" / "settings.local.json"):
        enabled.update(read_json(f).get("enabledPlugins", {}) or {})
    return [k for k, v in enabled.items() if v]


def plugin_dirs(root: Path):
    """Yield (plugin_name, dir) for each enabled plugin found on disk."""
    installed = read_json(CLAUDE_DIR / "plugins" / "installed_plugins.json")
    installed = installed.get("plugins", installed) if isinstance(installed, dict) else {}
    for key in enabled_plugins(root):
        name, _, market = key.partition("@")
        candidates = []
        entry = installed.get(key)
        for e in (entry if isinstance(entry, list) else [entry] if entry else []):
            if isinstance(e, dict) and e.get("installPath"):
                candidates.append(Path(e["installPath"]))
        mdir = CLAUDE_DIR / "plugins" / "marketplaces" / market
        candidates += [mdir / "plugins" / name, mdir / "external_plugins" / name]
        for c in candidates:
            if c.is_dir():
                yield name, c
                break


def md_items(directory: Path, kind: str, scope: str, prefix: str = ""):
    out = []
    if not directory.is_dir():
        return out
    for f in sorted(directory.rglob("*.md")):
        text = read_text(f)
        if text is None:
            continue
        meta, body = parse_frontmatter(text)
        rel = f.relative_to(directory).with_suffix("")
        name = meta.get("name") or ":".join(rel.parts)
        out.append({"id": display(f), "name": name,
                    "full_name": f"{prefix}:{name}" if prefix else name,
                    "description": meta.get("description", ""), "kind": kind,
                    "scope": scope, "path": display(f), "body": body})
    return out


def scan_tools(root: Path):
    skills = skills_in(root / ".claude" / "skills", "project")
    skills += skills_in(CLAUDE_DIR / "skills", "user")
    synced = CLAUDE_DIR / "skills" / "synced"
    if synced.is_dir():
        for bucket in sorted(synced.iterdir()):
            skills += skills_in(bucket, "synced", "anthropic-skills") if bucket.is_dir() else []

    commands = md_items(root / ".claude" / "commands", "command", "project")
    commands += md_items(CLAUDE_DIR / "commands", "command", "user")
    agents = md_items(root / ".claude" / "agents", "agent", "project")
    agents += md_items(CLAUDE_DIR / "agents", "agent", "user")

    for name, pdir in plugin_dirs(root):
        skills += skills_in(pdir / "skills", "plugin", name)
        commands += md_items(pdir / "commands", "command", "plugin", name)
        agents += md_items(pdir / "agents", "agent", "plugin", name)
    return skills, commands, agents


# ---------------------------------------------------------------- mentions

def mention_patterns(item):
    """Hyphenated/prefixed names match bare; single words need a cue
    (`/name`, `name`, "name skill", "skill name") to avoid false hits."""
    names = {item["name"], item.get("full_name", item["name"])}
    pats = []
    for n in names:
        e = re.escape(n)
        if "-" in n or ":" in n:
            pats.append(rf"(?<![\w-]){e}(?![\w-])")
        else:
            pats += [rf"(?<![\w-])/{e}(?![\w-])", rf"`/?{e}`",
                     rf"(?<![\w-]){e}\s+(skill|command|agent)",
                     rf"(skill|command|agent)\s+[`\"']?{e}(?![\w-])"]
    return re.compile("|".join(pats), re.IGNORECASE)


def find_mentions(items, context):
    for it in items:
        pat, hits = mention_patterns(it), []
        for ctx in context:
            for i, line in enumerate(ctx["body"].splitlines(), 1):
                if pat.search(line):
                    hits.append({"file": ctx["path"], "line": i, "text": line.strip()[:200]})
        it["mentions"] = hits


# ---------------------------------------------------------------- main

def build(root: Path):
    context = scan_context(root)
    skills, commands, agents = scan_tools(root)
    find_mentions(skills + commands + agents, context)
    return {"repo": str(root), "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "context": context, "skills": skills, "commands": commands, "agents": agents}


def render(data) -> str:
    payload = json.dumps(data).replace("</", "<\\/")
    return TEMPLATE.read_text(encoding="utf-8").replace("{{DATA}}", payload)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path", nargs="?", default=".", help="repo to scan (default: cwd)")
    ap.add_argument("--out", help="write HTML here instead of a temp file")
    ap.add_argument("--no-open", action="store_true", help="don't open a browser")
    ap.add_argument("--json", action="store_true", help="print raw scan data and exit")
    args = ap.parse_args(argv)

    root = repo_root(Path(args.path).resolve())
    data = build(root)
    if args.json:
        json.dump(data, sys.stdout, indent=2)
        return

    out = Path(args.out) if args.out else Path(tempfile.mkdtemp(prefix="skillscape-")) / "skillscape.html"
    out.write_text(render(data), encoding="utf-8")
    n_mentioned = sum(bool(i["mentions"]) for i in data["skills"])
    print(f"skillscape: {len(data['context'])} context files, {len(data['skills'])} skills "
          f"({n_mentioned} referenced), {len(data['commands'])} commands, "
          f"{len(data['agents'])} agents\n→ {out}")
    if not args.no_open:
        webbrowser.open(out.as_uri())


if __name__ == "__main__":
    main()
