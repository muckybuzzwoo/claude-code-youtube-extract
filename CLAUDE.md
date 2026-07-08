# CLAUDE.md — yt-extract plugin

Context for Claude Code when working inside this plugin repository.

## What this plugin is

`yt-extract` is a single-skill Claude Code plugin that extracts structured data
from YouTube videos (metadata, transcript, comments, screenshots) and produces a
Markdown file. The skill orchestrates a Python backend and dispatches one
subagent per URL for transcript summarization.

## Components

| Type   | Path                          | Purpose                                                        |
|--------|-------------------------------|----------------------------------------------------------------|
| Skill  | `skills/yt-extract/SKILL.md`  | User-invocable workflow (`/yt-extract`)                        |
| Script | `scripts/yt-extract.py`       | Python backend — yt-dlp + ffmpeg + VTT                         |
| Agent  | `agents/extract-worker.md`    | Restricted leaf worker the skill dispatches per URL (see below) |

Current version: **1.10.0** — see [CHANGELOG.md](CHANGELOG.md).

## Architectural conventions

- **Script invocation:** Always call the Python script via `${CLAUDE_PLUGIN_ROOT}/scripts/yt-extract.py`. Never use absolute or home-relative paths — the plugin must work regardless of install location.
- **Language:** All user-facing output (SKILL.md body, script stdout, README, CHANGELOG) is in English. Do not mix languages.
- **Section headers:** The Python script emits a fixed set of Markdown section headers (`### Metadata`, `### Description`, `### Chapters`, `### Transcript Info`, `### Transcript`, `### Screenshots`, `### Screenshot Status`, `### Comments`, `### Keyframes`). The SKILL.md subagent prompts parse these verbatim. If you rename a header, update both sides. `### Keyframes` is emitted only under `--visual`, among the content sections before the `OUTPUT_FOLDER:` trailer, and is **worker-consumed, not relayed** — the summarizer Reads the listed images, weaves observations into the summary, deletes the temp dir, and strips the section from its returned output. It is the only `###` section that does not pass through to the orchestrator.
- **Sentinel markers and orchestration trailers:**
  - Inside the `### Screenshots` section: `FFMPEG_MISSING` (defensive — Step 0.5 normally prevents this) and `SCREENSHOTS_ASK_USER` (since v1.8.0: only `--screenshots chapters` on a chapterless video; scene-detection mode, the default, never emits it). Since 1.8.1 the `extract-worker` subagent **returns** this marker — it cannot ask (no `AskUserQuestion` tool); the **orchestrator** asks the user for a strategy and re-dispatches the worker with explicit timestamps.
  - Stderr on exit code 2: `FOLDER_EXISTS: <path>` — target folder exists and `--force` was not passed. Since 1.8.1 the subagent **returns** the `FOLDER_EXISTS:` line (no AskUserQuestion in subagents); the **orchestrator** asks the user and re-dispatches with `--force`. The `--transcript-only` path runs in the main context, so it asks and re-runs inline.
  - Trailing stdout line on every successful run: `OUTPUT_FOLDER: <path>` — tells the skill where the script's target folder lives. Uses forward slashes, relative to CWD, and contains no spaces or colons. The script emits it with a trailing newline, but the orchestrator parses it from the **subagent's return**, where the harness can glue an `agentId: <hex>` trailer directly onto the line with no newline (e.g. `…_my-slugagentId: a2ba`). Since 1.8.2 the parse rule (SKILL.md Step 3) extracts the path by cutting at the first whitespace or the literal `agentId` substring — **not** by taking the raw last line, which would fold the trailer into the folder name. The `--transcript-only` path runs in the main context (no subagent boundary), so no trailer is appended there. The skill trims this line from the markdown before writing the `.md`. A static contract test (`test_skill_output_folder_parse_strips_harness_trailer`) asserts the rule's wording stays present.
  - Do not introduce new sentinels or trailers without updating the skill's handling block AND this list.
- **Stage markers on stderr:** The script emits `[k/N] <stage>` lines on stderr (flushed immediately) — metadata, transcript, comments (optional), scene-detection (optional, scene mode only — decodes the whole video, can take minutes), screenshots (optional), output. `N` is adaptive based on enabled flags. Subagent prompts tell subagents to forward these to the main chat as one-line updates.
- **Script owns output folder layout:** Since v1.2.0, the Python script creates the `yt-extract_<DATE>_<slug>/` folder and the `screenshots/` subfolder inside it directly. The skill does **not** do `mkdir`, `mv`, or `rmdir` for per-video layout. For multi-URL runs the skill creates the shared parent (`yt-extract_<DATE>_<N>-videos/`) before dispatch and passes it as `--output-base`.
- **Subagent dispatch:** Multi-URL runs dispatch one subagent per URL in parallel (single message, multiple Agent-tool calls). Preserve this pattern — sequential dispatch multiplies latency.
- **Worker agent (recursion guard — do not weaken):** Step 1 must dispatch `subagent_type: "yt-extract:extract-worker"`, **never `general-purpose`**. `agents/extract-worker.md` declares an explicit `tools` allowlist (`Bash, Read, Glob, Grep`) so the worker has no `Skill` and no `Agent` tool. This is structural, not cosmetic: a `general-purpose` worker inherits *all* tools, and because the skill is model-invocable (since v1.6.0 removed `disable-model-invocation: true`), such a worker re-invoked `/yt-extract` via the Skill tool, whose dispatch spawned another worker — an infinite recursion that burned tokens with no output (the 1.8.1 bug). Rules: (1) the `tools` allowlist must stay present and must exclude `Skill`/`Agent`/`Task` — omitting `tools` entirely silently reopens the loop; (2) the subagent prompts also carry a "you are a LEAF worker, do not invoke skills or dispatch agents" guard as defense-in-depth; (3) `tests/test_skill_contract.py` enforces both the dispatch target and the allowlist — keep it green. If you ever need the skill *not* model-invocable instead, re-add `disable-model-invocation: true` to the SKILL.md frontmatter (the v1.1.0–v1.5.0 guard), at the cost of programmatic invocation by other skills.

## Script CLI (internal, skill-facing)

The skill always passes these flags on dispatch — users never type them directly:

| Flag                | Purpose                                                                                             |
|---------------------|-----------------------------------------------------------------------------------------------------|
| `--output-base <d>` | Base directory. Script creates `<d>/yt-extract_<DATE>_<slug>/`. Default: `.` (CWD).                 |
| `--force`           | Overwrite an existing target folder. Without it, script exits `2` with `FOLDER_EXISTS:` on stderr.  |

User-facing flags (`--comments`, `--screenshots [scenes[=t]|chapters|timestamps]`, `--full-transcript`, `--transcript-only`, `--visual`, `--no-save`, `--check`) are parsed by the skill in Step 0.4, translated to their script equivalents where relevant, and passed down. Since v1.10.0, `--visual` is opt-in: it extracts 4 evenly-spaced, ephemeral keyframes to a temp dir and hands their paths to the summarizer worker via a `### Keyframes` section so the summary can address on-screen content (diagrams, code, slides); the worker deletes the temp dir after reading. Requires ffmpeg (checked in Step 0.5 alongside `--screenshots`). Ignored under `--full-transcript`/`--transcript-only` — those produce no summary to ground. Since v1.8.0, bare `--screenshots` means ffmpeg scene detection (`select` filter, default threshold 0.04 since v1.8.2 — was 0.025, two-pass: detect on a ≤360p stream, extract at ≤1080p; 4s min-gap, max 50 captures with even thinning). Since v1.9.0 a **perceptual dedup pass** runs after extraction in scenes mode only (`dedupe_screenshots` → `compute_thumbnail` + the pure `dedupe_perceptual_indices`/`frame_delta`): it compares 16×16 grayscale thumbnails and drops near-duplicates (mean-abs-diff ≤ `PERCEPTUAL_DEDUP_THRESHOLD` = 2.0 vs the last *kept* frame), deleting the dropped PNGs. Fail-open — any unbuildable thumbnail keeps every frame. The dropped count is not a sentinel or a WARNING: it flows as the `deduped` int into `render_screenshot_status`, which appends `, D near-duplicate(s) removed (K kept)` to the count line. `chapters`/`timestamps` captures are never deduped. `chapters` selects chapter markers (the pre-1.8.0 default; legacy value `auto` is an accepted alias). `--transcript-only` is also a script flag: it makes the script skip the metadata fetch, comments, and screenshots and emit only the `### Transcript Info` + `### Transcript` sections; the skill runs it directly (no subagent) and names the output folder by video ID.

## Out-of-scope changes

- **No hooks, no MCP servers, no other skills.** Keep the plugin to one skill + one script + the one internal `extract-worker` agent (added in 1.8.1 as the recursion guard — see Architectural conventions). If functionality must grow beyond that, propose splitting into a separate plugin.
- **Do not rename output folder schemes** (`yt-extract_DATE_slug/` for single-URL, `yt-extract_DATE_N-videos/` parent with nested per-video folders for multi-URL) without a migration note in CHANGELOG — downstream users may grep their filesystem for these. The multi-URL layout changed in v1.2.0 (per-video folders instead of flat `screenshots/slug/`); any further change is a breaking change.

## Testing

A small automated test layer covers the deterministic helper functions in
`scripts/yt-extract.py` — `slugify`, the timestamp formatters and parser,
the `render_*` helpers that build the fixed section headers, and the
scene-detection helpers (`parse_screenshots_mode`, `parse_scene_timestamps`,
`apply_min_gap`, `thin_evenly`). Since 1.8.1, `tests/test_skill_contract.py`
also covers the **skill ↔ worker-agent orchestration contract** by static file
parsing: it asserts Step 1 dispatches `yt-extract:extract-worker` (never
`general-purpose`) and that `agents/extract-worker.md` declares a `tools`
allowlist excluding `Skill`/`Agent`/`Task` — the invariant whose absence caused
the recursion loop. The tests are **pure Python**: they do not spawn `yt-dlp`,
`ffmpeg`, or any subprocess, and do not hit the network — so nothing beyond
`pytest` is required to run them.

**Requirements:** Python 3.8+. Dev dependency: `pytest` only.

```bash
pip install -r requirements-dev.txt
python -m pytest tests/
```

On Windows, `pip install` may place the `pytest` binary outside `PATH` (e.g. `%APPDATA%\Python\Python3XX\Scripts\`). Using `python -m pytest` avoids that — it works everywhere without requiring a PATH update.

Expected output: all tests pass in well under a second.

**Not covered by this unit suite:** subprocess invocations (`yt-dlp`,
`ffmpeg`), file I/O, network calls, VTT parsing, and the full `main()`
assembly with the trailing `OUTPUT_FOLDER:` marker. The orchestration layer is
covered only *statically* (the contract test parses files; it does not run a
real subagent dispatch) — whether a dispatched worker actually obeys "run the
Bash command, don't delegate" is LLM behavior that only an end-to-end run can
confirm. The 1.8.1 recursion lived precisely in this gap: a frontmatter/agent
wiring defect that no pure-Python test exercised. Broadening the automated
surface (subprocess fakes, a VTT fixture, golden-file tests for `main()`) is a
reasonable follow-up.

Manual verification still matters for the full integration path: install
the plugin locally and run `/yt-extract <real-youtube-url>` with and
without `--screenshots`, `--comments`, `--full-transcript`. Confirm the
auto-save folder layout and Markdown headers match the documented output
structure.

## Cross-platform invocation

The skill is expected to run on macOS, Linux, and Windows. Step 0 of SKILL.md
resolves OS-dependent values from lookup tables:

**Python launcher** (substituted as `<PY>` in subagent prompts):

| OS      | `<PY>`    |
|---------|-----------|
| Windows | `python`  |
| macOS   | `python3` |
| Linux   | `python3` |

Never hardcode `python` anywhere in SKILL.md — always use the placeholder.
The Python script itself is fully portable and needs no OS detection.

## Dependencies (install-on-demand)

Since v1.1.0, both system dependencies share a single install-on-demand flow
(SKILL.md Step 0.6). When a dependency is missing, the skill asks the user
whether to install it. When the detected OS has **multiple** valid install
methods for that dependency, the user picks which one. On failure, the user
sees an English error message with a link to the official documentation.

All install commands are written in a **non-interactive form** so the Claude
Code Bash tool — which has no stdin channel — never hangs on a license, a
y/n confirmation, or a sudo password prompt. The user-facing `AskUserQuestion`
dialog shows a short `label` (e.g. `winget`, `pip`), while the skill executes
the exact `command` below.

**yt-dlp** (required — always checked in Step 0.3):

| OS       | Options (label → executed command)                                                                                                     |
|----------|----------------------------------------------------------------------------------------------------------------------------------------|
| Windows  | `pip` → `pip install yt-dlp` **or** `winget` → `winget install yt-dlp --accept-package-agreements --accept-source-agreements --silent --disable-interactivity` (**user picks**) |
| macOS    | `brew` → `brew install yt-dlp` **or** `pip3` → `pip3 install --user yt-dlp` (**user picks**)                                           |
| Linux    | `pip` → `pip install --user yt-dlp` **or** `pipx` → `pipx install yt-dlp` (**user picks**)                                             |

Declining the yt-dlp install prompt aborts the skill with an error listing
both options. Doc URL: `https://github.com/yt-dlp/yt-dlp/wiki/Installation`.

**ffmpeg** (optional, only checked in Step 0.5 when `--screenshots` is set):

| OS       | Options (label → executed command)                                                                                                     |
|----------|----------------------------------------------------------------------------------------------------------------------------------------|
| Windows  | `winget` → `winget install Gyan.FFmpeg --accept-package-agreements --accept-source-agreements --silent --disable-interactivity`        |
| macOS    | `brew` → `brew install ffmpeg`                                                                                                         |
| Linux    | auto-detect pkg-mgr (see below)                                                                                                        |

**Linux ffmpeg + sudo:** The install helper (`skills/yt-extract/references/install-helper.md`, Step A0) probes `sudo -n true 2>/dev/null` first. If
there is no active sudo session (or no `NOPASSWD` rule), the helper does NOT
execute `sudo apt install -y ffmpeg` / `sudo dnf install -y ffmpeg` (it would
block on the password prompt). Instead it shows the exact manual commands to
the user and sets `skip_screenshots = true`. When `sudo -n` succeeds, the
install proceeds via the detected package manager.

Declining the ffmpeg install prompt sets `skip_screenshots` and continues
(no abort). Doc URL: `https://ffmpeg.org/download.html`.

**Design rules:**
1. When SKILL.md prompts the user for install choice, the options list in the
   `AskUserQuestion` call must match the matrix above for the detected OS. If
   you add a new valid install method for an OS, update both this matrix and
   the matrix in SKILL.md Step 0.2.
2. Every executable command in the matrix must be **non-interactive**. No
   prompts for license, confirmation, or sudo password may surface during
   Bash execution — they would hang the skill. Prefer `--user`-scope pip
   installs, winget `--accept-*-agreements` flags, and the `sudo -n` probe
   for any command requiring elevation.
3. **winget exit code 43** ("no upgrade available") means the package is already
   installed. The install helper's Step C treats this the same as exit 0 — proceed to
   Step D (verify). Do NOT treat it as a failed install (Step F). This matters
   because `yt-dlp.FFmpeg` (installed as a winget dependency of yt-dlp) and
   `Gyan.FFmpeg` can both exist, causing redundant installs with exit 43.
