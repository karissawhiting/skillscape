# skillscape

See everything Claude Code has available in a repo: instruction files, memory, rules, skills, commands and agents. Run it from inside a repo and it opens one HTML page with a card for each item. Click a card to expand it.

Skills, commands and agents that your instruction files name get a **★ referenced** badge, and the expanded card shows which file and line mention them.

## Install

``` sh
uv tool install git+https://github.com/karissawhiting/skillscape
# or
pipx install git+https://github.com/karissawhiting/skillscape
```

To try it once without installing:

``` sh
uvx --from git+https://github.com/karissawhiting/skillscape skillscape
```

To upgrade, run `uv tool upgrade skillscape`. You need Python 3.9 or later. It uses only the standard library.

## Usage

``` sh
skillscape                 # scan the current repo and open the page
skillscape ~/some/repo
skillscape --out map.html --no-open
skillscape --json          # raw scan data
```

From a clone without installing, run `python3 -m skillscape`.

## What it scans

- **Context:** `~/.claude/CLAUDE.md`, plus `CLAUDE.md` and `CLAUDE.local.md` in the repo root and every parent folder, `.claude/CLAUDE.md`, `@imports` (one level deep), `.claude/rules/`, and the project memory in `~/.claude/projects/<slug>/memory/`.
- **Skills:** project skills in `.claude/skills/`, user skills in `~/.claude/skills/`, skills synced from claude.ai in `~/.claude/skills/synced/`, and skills from the plugins enabled through `enabledPlugins` in your settings. A skill folder that's a symlink is grouped by the folder its link points into, so skills kept in category folders elsewhere show up in those categories. A skill nested one folder too deep is listed with a warning, because Claude Code may not load it.
- **Commands and agents:** the user, project and plugin `commands/` and `agents/` folders.

It never walks the rest of the repo. It also won't read anything under a folder whose name contains "data" or anything under `/Volumes/`. A skill in a folder like that is still listed, but its contents aren't read.

## How a match is counted

A name with a hyphen or a colon (`repo-triage`, `anthropic-skills:docx`) counts wherever it appears as a whole word. A one-word name needs a cue, so ordinary words like "pdf" or "docs" don't set it off. The cues are `/name`, `` `name` ``, "name skill" and "skill name".

## Limits

- Built-in skills (for example `artifact-design` and `code-review`) have no files on disk, so they can't be listed.
- `CLAUDE.md` files in subfolders load only when needed, and they aren't shown.
- MCP servers, hooks and permissions aren't shown yet.

## License

MIT