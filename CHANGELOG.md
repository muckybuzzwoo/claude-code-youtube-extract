# Changelog

All notable changes to `yt-extract` are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.7.0] — 2026-06-12

New lean `--transcript-only` mode: fetch and output just the raw transcript, no
metadata/description/chapters/comments/screenshots and no summary. It runs the
Python script **directly** (no subagent) because a subagent would only relay the
raw transcript back into context, paying its token cost twice. It also skips the
heavy `yt-dlp --dump-json` metadata call entirely, deriving the output folder
name from the video ID parsed out of the URL. Plus: a no-URL invocation now
always answers with a guided text message instead of failing.

### yt-extract.py (backend)

#### Added
- `extract_video_id(url)` — parses the 11-char YouTube video ID from `watch?v=`,
  `youtu.be/`, `/shorts/`, `/embed/`, and `/live/` URL forms; returns `None` on
  no match.
- `run_transcript_only(args)` — lean path that skips metadata, comments, and
  screenshots, emits only `### Transcript Info` + `### Transcript`, and reuses
  the existing `FOLDER_EXISTS` / `OUTPUT_FOLDER` contract.
- `--transcript-only` CLI flag — branches `main()` to `run_transcript_only()`
  right after argument parsing.

### yt-extract skill

#### Added
- `--transcript-only` flag (Step 0.4). When set, the skill runs the script
  directly per URL (parallel Bash calls for 2–3 URLs) with no subagent dispatch,
  emits a raw-transcript-only output format (no synthesis for multi-URL), and the
  "What next?" block offers an in-context summary as a follow-up instead of a
  separate summarized mode.
- No-URL handling (Step 0.4.a): when `/yt-extract` is reached with no URL (and
  without `--check`), it always answers with a plain-text message instead of
  failing — the full guided help when no flags were given, or a short "paste a
  URL" Rückfrage that preserves already-chosen flags. Never an `AskUserQuestion`,
  so it is safe in programmatic skill-to-skill calls.

#### Notes
- The happy path is unchanged: `/yt-extract <url>` still runs the default
  structured summary immediately; option discovery stays in the post-run "What
  next?" block (no upfront question wizard).
- `--transcript-only` reuses the existing `yt-extract_<DATE>_<slug>/` folder
  scheme (slug = video ID) — no folder-layout change, no migration needed.

### Docs

#### Changed
- Version reference bumped 1.6.0 → 1.7.0 across `CLAUDE.md`, `README.md` (badge,
  components table, footer), `.claude-plugin/plugin.json`, and
  `.claude-plugin/marketplace.json`.
- `README.md` — new Features bullet, Usage & Flags row, and example for
  `--transcript-only`.
- `CLAUDE.md` — `--transcript-only` documented in the Script CLI section.

- @mucky

## [1.6.0] — 2026-06-03

The skill can now be invoked **programmatically by other skills** via the Skill tool, not only manually via `/yt-extract`. Removing `disable-model-invocation: true` is what unblocks this — the Skill tool cannot reach a skill that declares that flag (per the Claude Code skills docs: "Use `disable-model-invocation: true` to block programmatic invocation"). Because the skill is now model-invocable, its `description` sits in context again, so it was tightened to fire only on an explicit extract/analyze request — replacing the hard flag as the over-trigger guard.

### yt-extract skill

#### Changed
- `SKILL.md` frontmatter — removed `disable-model-invocation: true`. The skill is now model-invocable and can be called from another skill via the Skill tool as `yt-extract:yt-extract <url> [flags]`. It stays user-invocable via `/yt-extract` (`user-invocable: true` is unchanged).
- `SKILL.md` `description` — tightened to trigger "only when explicitly asked to extract or analyze specific YouTube URL(s) … do not auto-trigger on incidental YouTube URL mentions or links shared merely as references". This soft guard replaces the hard `disable-model-invocation` block.
- `SKILL.md` "Extending this skill" line-count-budget note — no longer references the removed flag; the 500-line figure is now described as the soft guideline it is (it was never coupled to `disable-model-invocation`).

#### Behavior change
- The hard technical block against model-invocation is gone. Whether the skill auto-triggers on a stray YouTube link is now governed by the tightened `description` plus any user-level invocation gating (e.g. CLAUDE.md rules), not by a frontmatter flag. Set `disable-model-invocation: true` again to restore the hard block (at the cost of programmatic invocability).

### Docs

#### Changed
- Version reference bumped 1.5.0 → 1.6.0 across `CLAUDE.md`, `README.md` (badge, components table, footer), `.claude-plugin/plugin.json`, and `.claude-plugin/marketplace.json`.

## [1.5.0] — 2026-05-05

Windows-only fix for the "freshly installed but not on PATH" UX dead-end. `winget` installs into `%LOCALAPPDATA%\Microsoft\WinGet\Packages` with a shim under `\Microsoft\WinGet\Links\` — when that Links dir is empty or absent from the Bash tool's PATH, `yt-dlp --version` returned exit 127 even though the binary was on disk, and the skill's only response was "restart your terminal". v1.5.0 adds an automatic two-stage PATH-recovery step that locates the binary via merged-registry PATH and copies it into a directory already on the current shell's PATH (Stage 1 — Python's Scripts dir) or, as a fallback, into `WinGet\Links` while permanently adding that directory to the user PATH (Stage 2). One AskUserQuestion confirmation covers the full recovery chain.

### yt-extract skill

#### Added
- `references/install-helper.md` — new **Step W (Windows PATH Recovery)** with two recovery stages:
  - **Stage 1** copies the binary to Python's Scripts directory (already on PATH per the Step 0.3a Python check) — works in the current shell session, no Claude Code restart required.
  - **Stage 2** (auto-fallback when Stage 1 mechanically fails, or sole option when Stage 1 is unavailable, e.g. MS-Store Python) copies the binary to `%LOCALAPPDATA%\Microsoft\WinGet\Links` AND adds that directory to the user PATH via Registry — fixes the winget Links shim permanently for all future winget installs. Requires a Claude Code restart.
  - Step W locates the binary via PowerShell merged-registry `Get-Command` lookup with `Get-ChildItem` fallback under `%LOCALAPPDATA%\Microsoft\WinGet\Packages`.
- `SKILL.md` Step 0.3b (yt-dlp) and Step 0.5 (ffmpeg) — Windows pre-check fallback that invokes Step W BEFORE loading the install-helper. On Stage 1 success, the install-helper is skipped entirely (recovers the case where the binary is already on disk via winget but Bash cannot see it).
- `install-helper.md` Step D — Windows post-install fallback that invokes Step W BEFORE Step E. On Stage 1 success, returns success without "restart your terminal".
- ffmpeg recovery copies BOTH `ffmpeg.exe` and `ffprobe.exe` — yt-dlp invokes ffprobe internally for stream selection, so copying only `ffmpeg.exe` would yield silent screenshot failures.

#### Fixed
- Windows + winget yt-dlp / ffmpeg: skill no longer asks the user to install something that is already present on disk (Fall A — empty or absent `WinGet\Links` shim).
- Windows + fresh winget install: skill no longer aborts with "restart your terminal" for every freshly installed dependency (Fall B). One AskUserQuestion confirmation replaces the restart loop.
- Combined with the existing winget exit-code-43 normalization (install-helper.md Step C), `winget install yt-dlp` now resolves transparently when the binary is in the WinGet packages dir.

### Docs

#### Changed
- `README.md` Quick Start and Troubleshooting — rewrote the "expected first-time experience on Windows" guidance. The Claude Code restart is now the rare-case fallback, not the default ritual.
- `CLAUDE.md` — version reference bumped 1.4.0 → 1.5.0.

#### Known limitations
- After a future `winget upgrade` of a binary recovered via Stage 1 / Stage 2, the local copy goes stale until a fresh recovery runs. Mitigated by yt-dlp's built-in `-U` self-update; ffmpeg upgrades are rare. `/yt-extract --check` re-triggers recovery whenever needed.
- MS-Store Python users — both `sysconfig.get_paths()['scripts']` and `os.path.dirname(sys.executable)` resolve under `\WindowsApps\` with stub-redirect ACLs that reject `Copy-Item`. Step W detects this, suppresses Stage 1, and offers Stage 2 only (which writes to `WinGet\Links` and is unaffected by the ACL issue).

## [1.4.0] — 2026-04-24

Contributor-driven maintenance release. Two merged pull requests split off the install-on-demand helper from `SKILL.md`, refactored the Python script's markdown output into small pure `render_*` functions, and added a pytest-based unit suite for the deterministic helpers. No user-visible behavior changes — the markdown output and sentinel contracts are unchanged. Python 3.8 remains the minimum (the earlier 3.9 bump was reverted because `from __future__ import annotations` makes all generic-builtin annotations lazy).

### yt-extract skill

#### Added
- `skills/yt-extract/references/install-helper.md` — the previously inlined install-on-demand sub-workflow (Steps A0, A, B, C, D, E, F) is now a standalone reference. `SKILL.md` Step 0.6 loads it with the parameters `dep_name`, `options`, `doc_url`, `on_decline`, `verify_cmd`. Keeps `SKILL.md` lean; the helper can be updated without touching the main skill file.
- Step 0.3.a — Python runtime check (`<PY> --version`) runs before the yt-dlp check. Missing Python or an install-tool dialog (macOS CLT prompt, `command not found`) aborts immediately with an OS-specific message; earlier steps no longer silently skip it.
- `--check` mode also invokes `<PY> --version` so the readiness report includes the Python version alongside yt-dlp / ffmpeg.
- macOS yt-dlp install offers both `brew` and `pip3` (`pip3 install --user yt-dlp`). Previously brew-only.
- "Extending this skill" contributor section at the bottom of `SKILL.md` — points new contributors at `CLAUDE.md`, documents where to add a user-facing flag / install target / sentinel / Markdown section, and calls out the line-count budget relaxation from `disable-model-invocation: true`.

#### Changed
- UI emojis (✅, ℹ️, ❌, 💬, 💡) in `SKILL.md` prose replaced with plain text. The `👍` in `render_comments()` output is intentionally kept — it is part of the extracted markdown data, not the skill UI.
- Edge cases list cleaned up; the "Stream URL expired" entry that was accidentally dropped in the refactor has been restored with the intended re-run-once guidance.

### yt-extract.py (backend)

#### Added
- `from __future__ import annotations` at the top of the script — makes all generic-builtin annotations (`list[dict]`, `str | None`, etc.) lazy strings so the 3.8 minimum holds.
- Eight pure `render_*` helpers — `render_metadata`, `render_description`, `render_chapters`, `render_transcript_info`, `render_transcript`, `render_screenshots_section`, `render_screenshot_status`, `render_comments`. Each returns a string; `main()` assembles the final output with `"\n".join(section for section in sections if section)` and a single `print()`.

#### Changed
- `main()` no longer intersperses business logic with `print()` calls; extraction now happens first, then rendering, then a single flush. Output format is unchanged but the section boundaries now follow a consistent single-blank-line convention.

### Tests

#### Added
- `tests/test_rendering.py` — 26 pytest cases covering `slugify`, `format_timestamp_display`, `format_timestamp_filename`, `parse_timestamp`, and the `render_*` helpers. Module loading uses `importlib.util.spec_from_file_location` because the script filename contains a hyphen.
- `requirements-dev.txt` with a single dependency: `pytest>=8.0.0`.

#### Notes
- Run with `python -m pytest tests/`. On Windows, `pip install --user` places the bare `pytest` binary outside `PATH` — using `python -m pytest` avoids that without a PATH fix.

### Docs

#### Changed
- `README.md` — Python requirement labelled 3.8+ (badge was already 3.8+; the prose line is now aligned). Script description mentions "deterministic markdown rendering".
- `CLAUDE.md` — Testing section documents the pytest layout, the 3.8+ requirement, and the Windows-friendly `python -m pytest tests/` invocation. The install-helper matrices still reference the extracted helper via path instead of inline step numbers.

#### Migration notes
- Users who have already installed v1.3.0 need no action — the markdown output, folder layout, and CLI flags are identical. Run `/plugin update` to pick up the refactor.
- Contributors running tests for the first time on Windows: prefer `python -m pytest tests/` over bare `pytest` (see `CLAUDE.md`).

- @mucky

## [1.3.0] — 2026-04-20

Transcript quality fixes + structured full-transcript output. The VTT parser was leaking metadata headers and failing to dedup YouTube's rolling-caption 3-line window, producing `Kind: captions Language: en` at the top of transcripts and 2-3× word repetitions throughout. The chapter-aligned screenshot embedding from v1.1.0 also wasn't coordinated with `--full-transcript` mode — screenshots ended up both under `## Chapters` and inline in the transcript. All fixed in this release.

### yt-extract.py (backend)

#### Added
- `strip_overlap(prev, next)` helper — word-level longest suffix-prefix overlap strip. Handles YouTube auto-caption rolling windows where each cue repeats the tail of the previous cue (`[A,B,C] → [B,C,D] → [C,D,E]`). Idempotent for non-overlapping input.
- `_is_chapter_aligned(screenshots, chapters)` helper — detects whether a screenshot run matches the chapter list 1:1 within 1s timestamp tolerance. Used to pick the transcript render strategy.
- `_chapter_end_time(chapters, idx)` helper — defensive fallback for chapters missing `end_time` (falls back to next chapter's `start_time`, then `+inf`).
- **Chapter-structured transcript rendering**: when `--full-transcript` + `--screenshots` run chapter-aligned, the transcript is now emitted as a sequence of `### [HH:MM] Chapter Title` h3 blocks, each followed by the matching screenshot and then the transcript segments that fall within that chapter's time interval.
- **Inline-with-heading fallback**: for non-chapter-aligned runs (custom timestamps or count mismatch), each inline screenshot now gets a preceding `### [HH:MM]` h3 heading (or `### [HH:MM] — Chapter Title` if the timestamp happens to fall inside a chapter) so readers see the context, not just an anonymous image.

#### Changed
- VTT parser skip-patterns extended: `Kind: ...` and `Language: ...` header fields are now skipped. `NOTE` and `STYLE` blocks are tracked and their bodies skipped until the next blank line.
- Dedup replaced: the old per-line + per-segment "consecutive identical" check is replaced by a single cue-based suffix-prefix overlap-strip pass. Catches both identical-cue duplicates and the rolling-window overlaps the old logic missed.
- `embed_screenshots_in_transcript()` now dispatches to `_render_chapter_structured()` or `_render_inline_with_heading()` based on the new alignment detection — previously a single inline-insert path for both cases.

#### Fixed
- **VTT metadata leak**: `Kind: captions`, `Language: <lang>`, and unclosed `NOTE`/`STYLE` block contents no longer appear as the first "words" of the transcript.
- **Triple word repetition** (YouTube auto-caption rolling window): "the updates never stop the updates never stop the updates never stop just released..." — now collapsed to a single pass via the new overlap-strip.
- **Duplicate images in `--full-transcript` mode**: screenshots previously appeared both under `## Chapters` AND inline in the transcript. Script now emits them only inline (as h3 blocks); `## Chapters` becomes a plain TOC in full-transcript mode (see skill change below).
- **Duplicated text around inline images**: this was the same rolling-caption bug manifesting at cue boundaries where screenshots were inserted. Fixed transitively by the dedup rewrite.

### yt-extract skill

#### Changed
- **`## Chapters` rule split by mode.** Summary mode (default): chapter-aligned screenshots still embedded under each chapter line as in v1.2.0. `--full-transcript` mode: chapters render as a plain TOC — screenshots live in the transcript section with h3 headings.
- **`## Transcript` in `--full-transcript` mode**: subagent output is now pre-structured by the Python script with `### [HH:MM] ...` sub-headings, each followed by the matching screenshot and the transcript text for that interval. The skill uses the output verbatim — no post-processing needed in single-URL mode.
- **Multi-URL `### Transcript` (full-transcript mode)**: new one-pass heading-demote applied to each subagent's transcript text before consolidation — `^### ` → `#### ` — so the script's h3 chapter-sub-headings nest correctly under the surrounding `### Transcript` h3 section.
- **`## Screenshots` conditional rendering** extended with a clause for `--full-transcript` + custom timestamps: OMIT (already embedded with h3 headings inside the transcript). Standalone list is now reserved strictly for summary mode with non-chapter-aligned screenshots.

#### Migration notes
- Saved v1.2.0 full-transcript + screenshots files render identically to before (same file paths, same images). The structural improvements apply only to newly generated files.
- The README diagram showing the old inline-only embedding is now labelled "summary mode"; the new chapter-structured layout is documented in the Anatomy section.

- @mucky

## [1.2.0] — 2026-04-20

Script-owned output folder layout and deterministic progress output. The intermediate `yt-screenshots/` staging folder is gone — the Python script now writes directly into the final `yt-extract_<DATE>_<slug>/` folder, with screenshots in a sibling `screenshots/` subfolder. The skill only orchestrates `--output-base` and saves the consolidated markdown.

### yt-extract.py (backend)

#### Added
- `--output-base <dir>` CLI flag (default: current directory). The script creates `<base>/yt-extract_<DATE>_<slug>/` and writes screenshots into `<base>/yt-extract_<DATE>_<slug>/screenshots/` directly. No more staging, no moves, no rmdir cleanup.
- `--force` CLI flag — overwrite an existing target folder. Without it, the script exits with code `2` and emits `FOLDER_EXISTS: <path>` on stderr so the caller can ask the user.
- **Progress stage markers on stderr.** The script emits lines like `[1/5] Fetching metadata...`, `[2/5] Downloading transcript...`, `[3/5] Extracting 7 screenshots...`, flushed immediately. Stage count is adaptive — `[1/3]` for metadata + transcript + output, `[1/5]` when `--comments` and `--screenshots` are both set, etc. Visible in the Bash tool output during runs.
- **`OUTPUT_FOLDER: <path>` trailer** as the final stdout line of every successful run. The skill parses it to decide where to write the consolidated markdown. Uses forward slashes so it is stable across platforms.

#### Changed
- `extract_screenshots()` signature: takes `out_dir` directly instead of constructing `yt-screenshots/<slug>` from `slug`. Returns `(timestamp, filename)` tuples instead of `(timestamp, full_path)` — callers build the markdown-relative path themselves.
- The `### Screenshots` section no longer emits a `screenshot_dir:` line. Image paths in the markdown are now plain relative paths (`screenshots/NNN_HHmmss.png`) resolved against the folder where the MD lives.
- The script now creates the target folder unconditionally after metadata fetch (before transcript/screenshot work). The collision guard runs before creation, so re-runs without `--force` fail cleanly.

### yt-extract skill

#### Added
- `--output-base` and `--force` are passed by the skill automatically — users do not need to specify them. `--output-base .` for single-URL runs, `--output-base ./yt-extract_<DATE>_<N>-videos` for 2–3-URL runs (parent folder created before dispatch).
- **Narration block before subagent dispatch.** For 1 URL: `Extracting from <url>. This typically takes 30–60 seconds...`. For 2–3 URLs: `Dispatching <N> parallel extractions...`. As each subagent returns, a one-line status is surfaced.
- **Progress surfacing in subagent prompts.** Subagents are now instructed to forward the `[k/N]` stage markers they see on stderr as one-line updates, so the main chat keeps showing motion during long-running extractions.
- **FOLDER_EXISTS handling.** If the script exits with code 2 and `FOLDER_EXISTS: <path>` is on stderr, the subagent asks the user via `AskUserQuestion` and re-runs with `--force`. For multi-URL runs, the skill also checks the parent folder upfront and asks before dispatching any subagents.
- Parent folder for multi-URL runs is created explicitly by the skill before subagent dispatch (`mkdir -p ./yt-extract_<DATE>_<N>-videos`).

#### Changed
- **Auto-save flow radically simplified.** The old 8-step flow (mkdir → move screenshots → rewrite paths → rmdir staging) collapses to: read `OUTPUT_FOLDER:` from subagent output → prepend YAML frontmatter → write MD. For multi-video consolidation, the only path rewrite is prefixing each video's paths with its per-video folder name. No filesystem moves.
- **`--no-save` semantics.** Script always creates the target folder (required for screenshots + `OUTPUT_FOLDER:` trailer). When the user declines saving at the end, the skill now removes the folder with `rm -rf` instead of leaving it orphaned.
- **Multi-URL folder layout.** Each video lives in its own per-video folder inside the parent (`./yt-extract_DATE_N-videos/yt-extract_DATE_slug1/screenshots/`), instead of sharing a flat `./yt-extract_DATE_N-videos/screenshots/slug1/` layout. Each per-video folder is now a complete, standalone extraction unit.

#### Removed
- The intermediate `yt-screenshots/` top-level folder and all related staging / move / cleanup logic.
- The `screenshot_dir:` line from the `### Screenshots` section — redundant with the new `OUTPUT_FOLDER:` trailer.
- The "Shell-command hygiene" warning block in Step 3 that applied to the old `mv` + `Measure-Object` flow.

#### Migration notes
- Standalone script users (`python scripts/yt-extract.py <url>`) will see a new folder `./yt-extract_<DATE>_<slug>/` in their CWD where previously only `yt-screenshots/<slug>/` appeared. This is the intended new behavior.
- Multi-URL consolidated markdown references screenshots via a deeper path (`yt-extract_DATE_slug1/screenshots/...` instead of `screenshots/slug1/...`). Old saved markdown files still render correctly because they use relative paths — only the relative structure inside new folders changes.
- In the rare multi-URL + FOLDER_EXISTS race (two subagents hit a collision simultaneously), users may see more than one `AskUserQuestion` prompt in parallel. Known limitation; acceptable for now.

- @mucky

## [1.1.0] — 2026-04-17

Unified install-on-demand flow for both system dependencies (yt-dlp and ffmpeg),
with per-OS install commands, user choice when multiple install methods are valid,
and actionable error messages that link to the official documentation.

### yt-extract skill

#### Added
- yt-dlp install-on-demand: when yt-dlp is missing, the skill now offers to install it via `AskUserQuestion` instead of hard-aborting. On Windows and Linux, the user picks between valid options (Windows: pip vs winget; Linux: pip vs pipx). macOS runs `brew install yt-dlp` behind a confirmation.
- ffmpeg install check moved to Step 0.5 — fires **only** when `--screenshots` is requested, and **before** subagent dispatch. Multi-URL runs now produce exactly one ffmpeg prompt instead of one per subagent.
- Install-dependency helper (Step 0.6) — shared flow for both deps: ask → run → verify → on verification failure show "restart your terminal" hint and abort with doc link.
- Doc URLs surfaced in every failure path: `https://github.com/yt-dlp/yt-dlp/wiki/Installation` and `https://ffmpeg.org/download.html`.
- Linux ffmpeg install auto-detects apt vs dnf via `command -v` (no user prompt for distro-determined choice).
- **Non-interactive install commands across the board** so Bash calls never hang on a license, confirmation, or sudo password prompt:
  - Windows winget commands now include `--accept-package-agreements --accept-source-agreements --silent --disable-interactivity`.
  - Linux pip for yt-dlp is `pip install --user yt-dlp` (user-scope, no sudo).
  - Linux ffmpeg install is gated by a `sudo -n true` probe: if no active sudo session exists, the helper does NOT attempt the install (avoids the password hang) and instead shows the exact manual command for the user to run, then sets `skip_screenshots`.
- Install-option entries in the Step 0.2 matrix now use a `{label, command}` pair: the short label (e.g. `winget`, `pip`) appears in `AskUserQuestion`, while the full non-interactive command is what the helper actually executes.
- `--check` flag — verify dependencies without doing any video extraction. Runs Step 0 (OS detection, `yt-dlp` check, optional `ffmpeg` check when combined with `--screenshots`), prints a readiness report, and stops. URLs are ignored in check mode. Primary use case: first-time install verification and the Windows shell-restart retry loop, without generating Markdown files or fetching video data.
- **Chapter-aligned screenshot embedding.** When `--screenshots` is taken at chapter markers (default behavior when no explicit timestamps are passed), screenshots are now embedded directly below each entry in the `## Chapters` section of the saved Markdown — one image per chapter line, in context. The standalone `## Screenshots` section is suppressed in this case to avoid duplication. Custom-timestamp screenshots (`--screenshots 0:30,2:15,...`) still render as a standalone list because they cannot be mapped to chapters.
- **"What next?" follow-up invitation.** Every successful run ends with a concise, context-aware block that lists 3–4 concrete follow-up queries (extract tools as a checklist, write a blog draft, drill into a specific chapter, translate the summary) plus re-run hints for any flags not used in the current invocation (`--comments`, `--full-transcript`, `--screenshots`) and a `/yt-extract url1 url2` compare hint for single-URL runs. Makes it obvious that the extracted transcript + summary remain in the Claude Code session's context and can be queried further without re-running. The block is suppressed in `--check` mode and on error paths.

#### Changed
- yt-dlp missing no longer silently aborts with a one-line error — it now runs through the full install-on-demand helper.
- Subagent prompts (default and `--full-transcript`) no longer handle `FFMPEG_MISSING` — Step 0.5 guarantees ffmpeg presence or skip-screenshots before dispatch. The sentinel is still emitted by the Python script as defense-in-depth but should not be reached in normal flow.
- Declining the ffmpeg install prompt now sets a `skip_screenshots` flag and continues (previously: continue silently). The final output notes why screenshots were skipped.

#### Fixed
- Step 0.6.C now treats winget exit code `43` ("no upgrade available" — package already installed) the same as exit 0, proceeding to Step D for PATH verification. Previously, exit 43 would have incorrectly triggered Step F ("Failed to install") and aborted the skill. This matters because `winget install yt-dlp` pulls `yt-dlp.FFmpeg` as a dependency — when the user later accepts a `Gyan.FFmpeg` install, winget reports "already installed" with exit 43, and without the fix the skill would misread this as a failure.

- @mucky

## [1.0.0] — 2026-04-16

Initial public release. Migrated from the private `yt-analyze` command to a distributable
Claude Code plugin.

### yt-extract skill

#### Added
- `/yt-extract <url>` skill (replaces `/yt-analyze`)
- Structured transcript summary: Core Thesis, Main Points, Tools & Resources, Key Quotes & Numbers
- Raw transcript mode via `--full-transcript`
- Top-10 comments via `--comments`
- Screenshot extraction via `--screenshots` (chapter markers or custom timestamps)
- Multi-video mode (2-3 URLs) with parallel subagent dispatch and cross-video synthesis
- Auto-save into dated folders with YAML frontmatter and organized screenshots
- `--no-save` flag to opt out of auto-save
- `FFMPEG_MISSING` and `SCREENSHOTS_ASK_USER` sentinel markers for Claude-mediated resolution
- `allowed-tools` scoping in frontmatter: `Bash, Agent, Write, Read, AskUserQuestion`
- `<user_request>` wrapper around `$ARGUMENTS` for prompt-injection safety
- URL filter accepts `youtube.com`, `www.youtube.com`, `m.youtube.com`, `youtu.be`

- OS-aware script invocation: Windows uses `python`, macOS/Linux uses `python3` — resolved in Step 0 and substituted via `<PY>` placeholder
- OS-aware ffmpeg install prompt: `winget install Gyan.FFmpeg` (Windows) / `brew install ffmpeg` (macOS) / `apt install ffmpeg` or `dnf install ffmpeg` (Linux)
- yt-dlp install hint also OS-specific (brew / pip+pipx / pip+winget)
- Post-save confirmation reads the screenshot count from the script's `### Screenshot Status` output instead of running a filesystem `Measure-Object` pipeline — prevents noisy PowerShell permission prompts on Windows

#### Changed
- Renamed: `yt-analyze` → `yt-extract`
- Output folder name: `yt-analyze_DATE_slug/` → `yt-extract_DATE_slug/`
- Script path: `~/.claude/scripts/yt-extract.py` → `${CLAUDE_PLUGIN_ROOT}/scripts/yt-extract.py`
- All user-facing output translated from German to English

### yt-extract.py (backend)

#### Added
- Chapter extraction and output
- VTT parser with timestamp preservation for screenshot alignment inside transcripts
- ffmpeg availability check with sentinel output
- `screenshot_dir:` hint inside the `### Screenshots` section for auto-save handlers

#### Changed
- All section headers translated from German to English (`### Metadata`, `### Description`, `### Chapters`, `### Transcript`, `### Comments`, `### Screenshot Status`)
- All warning and status messages translated to English

- @mucky
