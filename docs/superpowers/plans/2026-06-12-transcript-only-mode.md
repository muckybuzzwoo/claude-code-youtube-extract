# `--transcript-only` Mode + Guided Bare-Invocation UX — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a lean `--transcript-only` mode that fetches and outputs just the raw transcript (no metadata/summary/subagent), plus a guided help message when `/yt-extract` is invoked without a URL.

**Architecture:** Reuse the existing yt-dlp transcript path (`download_and_process_vtt`) but skip the heavy metadata `--dump-json` call — derive the output-folder slug from the video ID parsed out of the URL. The skill runs the script *directly* (no subagent) for this mode, because a subagent would only relay the raw transcript back, doubling its token cost for zero summarization benefit. No new pip dependency: `youtube-transcript-api` is explicitly **not** part of this plan (see "Explicitly out of scope").

**Tech Stack:** Python 3.8+ (stdlib only), yt-dlp (binary on PATH), pytest for the one new pure helper, Markdown SKILL.md orchestration.

---

## Background & Decisions (read before starting)

This plan is the agreed "lean counter-proposal" from the design discussion. The rationale and the ideas that were **rejected** are captured here so the implementer does not re-introduce them:

- **Why no subagent for this mode.** The default mode uses a subagent to *compress* a long transcript into a small summary, keeping the main context light. When the deliverable is the *raw* transcript, a subagent provides no compression — it ingests the transcript (input tokens) and relays it back (the relayed text re-enters the main context), so the transcript is paid for twice. Running the script directly pays once.
- **Why skip the metadata fetch.** `yt-dlp --dump-json` is a full extractor run (the expensive call). Transcript-only needs no title/views/chapters, so skipping it roughly halves the yt-dlp work. The cost: no human-readable title for the filename → we use the video ID, with a one-line note to the user. This was explicitly accepted during design.
- **The "summarize the transcript" need is met as a follow-up, not a mode.** Instead of a separate "transcript-only but summarized" mode (which would duplicate ~90% of the existing default mode), the raw transcript lands in context and the "What next?" block offers "Summarize it". One in-context follow-up, no new mode.
- **Bare-invocation UX is a help message, not a step-by-step wizard.** A multi-question `AskUserQuestion` flow on the happy path (`/yt-extract <url>`) was rejected: it punishes the most common case and conflicts with the user's global rule "URL + analyze request → just do it". It also risks firing in programmatic (skill-to-skill) invocation where no human can answer. The agreed design: bare `/yt-extract` (no URL) prints a guided help and stops; `/yt-extract <url>` runs the default immediately and surfaces options via the existing "What next?" block.

### Explicitly out of scope (do NOT implement)
- `youtube-transcript-api` library integration / yt-dlp fallback — separate future optimization, needs a pip dependency, not part of this release.
- Cheaper subagent model selection — the only subagent (the summary) is the quality-critical, hallucination-sensitive deliverable; savings are negligible.
- A "transcript-only summarized" sub-mode — redundant with the default mode; covered by the follow-up offer instead.

### Resolved decision: no AskUserQuestion; text Rückfrage on missing URL
The missing-URL case is handled by a **plain-text** message (Task C1), never an `AskUserQuestion` dialog — text is safe in programmatic skill-to-skill invocation where no human can answer. Two layers, do not conflate them:
- **Layer 2 (skill guard, this plan's Task C1):** sees only `$ARGUMENTS`. When no URL is present it always answers — full help if no flags were given, or a short flag-preserving Rückfrage if flags were passed. It cannot know natural-language intent.
- **Layer 1 (orchestrator behavior, NOT a skill-file change):** when the user describes a video in chat without a URL, the orchestrating Claude asks conversationally for the URL while preserving any options the user already stated or paraphrased ("nur das Transkript" → `--transcript-only`), and only then invokes the skill. Governed by the user's global CLAUDE.md YouTube rule. It is intentionally not encoded in the skill file (the skill never sees the chat sentence). Because the orchestrator invokes the skill only once it has a URL, Task C1's guard fires solely for a literally empty `/yt-extract` — no double prompt.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `scripts/yt-extract.py` | Python backend | Add `extract_video_id()` helper; add `run_transcript_only()`; wire `--transcript-only` arg into `main()` |
| `tests/test_rendering.py` | Pure unit tests | Add `extract_video_id` cases (the only new unit-testable surface) |
| `skills/yt-extract/SKILL.md` | Orchestration | Bare-invocation guard (Step 0.4); flag parsing; direct-run branch (Step 1); output format (Step 2); save + What-next (Step 3) |
| `CLAUDE.md` | Skill↔script contract | Document `--transcript-only` in the CLI tables; bump version |
| `README.md` | User docs | Features bullet, Usage table, Examples, version refs |
| `CHANGELOG.md` | Release notes | New `[1.7.0]` entry |
| `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` | Plugin manifest | Version bump 1.6.0 → 1.7.0 |

**Testing reality (from `CLAUDE.md`):** Only pure, deterministic helpers are unit-tested. `extract_video_id` is pure → TDD it (Task A1). `run_transcript_only` does subprocess + file I/O → it is verified manually (Task D6), consistent with how `main()` and all yt-dlp/ffmpeg paths are already handled. Do not try to unit-test subprocess calls.

**Version:** 1.6.0 → **1.7.0** (new backward-compatible feature = minor bump).

---

## Group A — Backend: `--transcript-only` (scripts/yt-extract.py)

### Task A1: `extract_video_id()` helper (TDD)

**Files:**
- Modify: `scripts/yt-extract.py` (add helper in the `# --- Utility functions ---` block, near `slugify`)
- Test: `tests/test_rendering.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_rendering.py` (after the slugify tests, keep the existing `# ---` section style):

```python
# --- extract_video_id ---


def test_extract_video_id_watch_url():
    assert (
        yt_extract.extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        == "dQw4w9WgXcQ"
    )


def test_extract_video_id_short_url():
    assert yt_extract.extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_extract_video_id_shorts_url():
    assert (
        yt_extract.extract_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ")
        == "dQw4w9WgXcQ"
    )


def test_extract_video_id_ignores_trailing_query_params():
    assert (
        yt_extract.extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s")
        == "dQw4w9WgXcQ"
    )


def test_extract_video_id_returns_none_on_no_match():
    assert yt_extract.extract_video_id("https://example.com/not-a-video") is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_rendering.py -k extract_video_id -v`
Expected: FAIL — `AttributeError: module 'yt_extract' has no attribute 'extract_video_id'`.

- [ ] **Step 3: Implement the helper**

Add to `scripts/yt-extract.py` immediately after the `slugify()` function (around line 53):

```python
def extract_video_id(url: str) -> str | None:
    """Extract the 11-char YouTube video ID from common URL forms
    (``watch?v=``, ``youtu.be/``, ``/shorts/``, ``/embed/``). Returns None on
    no match. Used by --transcript-only mode to name the output folder
    without paying for a metadata fetch.
    """
    m = re.search(r"(?:v=|/shorts/|/embed/|youtu\.be/)([A-Za-z0-9_-]{11})", url)
    return m.group(1) if m else None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_rendering.py -k extract_video_id -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/yt-extract.py tests/test_rendering.py
git commit -m "feat(script): add extract_video_id helper for transcript-only mode"
```

---

### Task A2: `run_transcript_only()` + `--transcript-only` arg

**Files:**
- Modify: `scripts/yt-extract.py` (add `run_transcript_only()` before `main()`; add arg + early branch in `main()`)

- [ ] **Step 1: Add the `run_transcript_only()` function**

Insert directly above `def main():` (around line 709):

```python
def run_transcript_only(args: argparse.Namespace) -> None:
    """Lean path: fetch and emit ONLY the raw transcript. No metadata fetch,
    no comments, no screenshots, no summary. Names the output folder by the
    video ID parsed from the URL (falls back to a URL-derived slug).
    """
    url = args.url
    total_stages = 2

    emit_stage(1, total_stages, "Downloading transcript")
    video_id = extract_video_id(url)
    slug = video_id or ("video-" + slugify(url, 40))

    date_str = datetime.date.today().isoformat()
    target = os.path.join(args.output_base, f"yt-extract_{date_str}_{slug}")

    if os.path.isdir(target) and not args.force:
        print(f"FOLDER_EXISTS: {target}", file=sys.stderr, flush=True)
        sys.exit(2)
    os.makedirs(target, exist_ok=True)

    transcript, sub_hint, segments = download_and_process_vtt(url, video_id or "ytx")

    emit_stage(2, total_stages, "Writing output")
    sections = [
        render_transcript_info(sub_hint, 0),
        render_transcript(transcript, segments, [], []),
    ]
    print("\n".join(section for section in sections if section))
    print()
    print(f"OUTPUT_FOLDER: {target.replace(os.sep, '/')}")
```

Notes for the implementer:
- This reuses `emit_stage`, `extract_video_id`, `slugify`, `download_and_process_vtt`, `render_transcript_info`, `render_transcript`, and the same `FOLDER_EXISTS` / `OUTPUT_FOLDER` contract as `main()`. No new sentinels.
- `render_transcript_info(sub_hint, 0)` passes duration 0 → the ">3600s" line is correctly skipped (no duration available without metadata).
- `render_transcript(transcript, segments, [], [])` passes empty screenshots/chapters → it emits the plain raw transcript.

- [ ] **Step 2: Add the `--transcript-only` argument in `main()`**

In `main()`, after the `--force` argument block (around line 729), add:

```python
    parser.add_argument(
        "--transcript-only", action="store_true",
        help="Fetch and output ONLY the raw transcript — no metadata, "
             "description, chapters, comments, or screenshots. Skips the "
             "metadata fetch; names the output folder by video ID.",
    )
```

- [ ] **Step 3: Branch to the lean path right after arg parsing**

In `main()`, immediately after `args = parser.parse_args()` (line 730) and before `url = args.url`, add:

```python
    if args.transcript_only:
        run_transcript_only(args)
        return
```

- [ ] **Step 4: Smoke-check that argument parsing still works (no network)**

Run: `python scripts/yt-extract.py --help`
Expected: help text lists `--transcript-only`; exit 0. (Full network run is Task D6.)

- [ ] **Step 5: Run the full unit suite (nothing regressed)**

Run: `python -m pytest tests/ -v`
Expected: all existing tests + the 5 new `extract_video_id` tests pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/yt-extract.py
git commit -m "feat(script): add --transcript-only mode (raw transcript, no metadata fetch)"
```

---

## Group B — Orchestration: `--transcript-only` (skills/yt-extract/SKILL.md)

> SKILL.md is prose orchestration, not executable code — these tasks edit Markdown. There is no unit test; correctness is verified by Task D6 (manual run) and Task D5 (review). Commit each task.

### Task B1: Parse the `--transcript-only` flag (Step 0.4)

**Files:** Modify `skills/yt-extract/SKILL.md` (Step 0.4 "Parse flags" list, around line 136)

- [ ] **Step 1: Add the flag to the parse list**

After the `--check` bullet in Step 0.4, add:

```markdown
- `--transcript-only` → fetch and output ONLY the raw transcript: no metadata, description, chapters, comments, screenshots, or LLM summary, and **no subagent** (the skill runs the script directly). When set, `--comments`, `--screenshots`, and `--full-transcript` are ignored — transcript-only is the leanest mode. Combinable with `--no-save`.
```

- [ ] **Step 2: Commit**

```bash
git add skills/yt-extract/SKILL.md
git commit -m "docs(skill): parse --transcript-only flag (Step 0.4)"
```

---

### Task B2: Direct-run branch, no subagent (Step 1)

**Files:** Modify `skills/yt-extract/SKILL.md` (Step 1, before "When --full-transcript is NOT set", around line 245)

- [ ] **Step 1: Add the transcript-only dispatch branch**

Insert this subsection at the start of Step 1's dispatch logic (before the default-mode subagent prompt):

````markdown
### When `--transcript-only` IS set (no subagent):

Do **not** dispatch subagents. The raw transcript is the deliverable; a subagent would only relay it back into the main context, paying for the transcript twice for zero summarization benefit. The skill runs the script directly via Bash.

**1 URL** — one Bash call (substitute `<PY>` from Step 0.1):

```bash
<PY> "${CLAUDE_PLUGIN_ROOT}/scripts/yt-extract.py" "[URL]" --transcript-only --output-base "."
```

**2-3 URLs** — create the parent folder first, then issue one Bash call per URL **in a single message (parallel tool calls)**:

```bash
mkdir -p "./yt-extract_[DATE]_[N]-videos"
```
then per URL:
```bash
<PY> "${CLAUDE_PLUGIN_ROOT}/scripts/yt-extract.py" "[URL]" --transcript-only --output-base "./yt-extract_[DATE]_[N]-videos"
```

**Stage markers:** the script emits `[1/2] Downloading transcript` and `[2/2] Writing output` on stderr — surface each as a one-line update.

**FOLDER_EXISTS (exit code 2):** identical handling to the other modes — if a Bash call exits 2 with `FOLDER_EXISTS: <path>` on stderr, ask via AskUserQuestion ("Folder already exists. Overwrite?") and re-run that exact command with `--force` appended.

**Parse `OUTPUT_FOLDER: <path>`** (the last stdout line of each run) to locate each target folder for saving. Trim it from the transcript text before formatting.
````

- [ ] **Step 2: Commit**

```bash
git add skills/yt-extract/SKILL.md
git commit -m "docs(skill): add transcript-only direct-run branch (Step 1)"
```

---

### Task B3: Output format for transcript-only (Step 2)

**Files:** Modify `skills/yt-extract/SKILL.md` (Step 2, after the multi-URL format block, around line 442)

- [ ] **Step 1: Add the transcript-only formatting section**

````markdown
### Transcript-only output (when `--transcript-only` is set):

The script emits only `### Transcript Info` and `### Transcript`. Format as:

**1 URL:**
```
## Transcript — [video ID]
> Note: transcript-only mode — output folder/file is named by the video ID (no metadata was fetched).
> [If auto-generated:] Note: Auto-generated subtitles ([language])

[raw transcript verbatim from the script's ### Transcript section]
```

**2-3 URLs:** one `## Transcript [i] — [video ID]` section per video, in input order. **No Synthesis section** — transcript-only is raw data, not cross-video analysis.

If a video has no transcript, render `> No transcript available.` for that video and continue.
````

- [ ] **Step 2: Commit**

```bash
git add skills/yt-extract/SKILL.md
git commit -m "docs(skill): add transcript-only output format (Step 2)"
```

---

### Task B4: Save, frontmatter & What-next for transcript-only (Step 3)

**Files:** Modify `skills/yt-extract/SKILL.md` (Step 3, around the frontmatter + What-next blocks, lines 500–562)

- [ ] **Step 1: Note the frontmatter values for transcript-only**

In the YAML frontmatter subsection, add a note:

```markdown
**Transcript-only mode:** no metadata is fetched, so for the single-video frontmatter set `title: "[video ID]"` and omit `channel`/`date` (use `url` and `analyzed` as usual). `flags` includes `transcript-only`. Filename derives from the `OUTPUT_FOLDER` last path segment exactly as in the other modes.
```

- [ ] **Step 2: Add the transcript-only "What next?" variant**

In the Follow-up invitation subsection, add:

```markdown
**Transcript-only variant of the What-next block:** the raw transcript is in context, so offer the summary as a follow-up instead of as a separate mode:

```
**What next?** The raw transcript is in context — you can ask me to:
- Summarize it (Core Thesis, Main Points, Tools & Resources, Quotes & Numbers)
- Extract all tools & resources as a checklist
- Translate it to another language

Or re-run for the full treatment:
- Drop `--transcript-only` for metadata + a structured summary
```
```

- [ ] **Step 3: Commit**

```bash
git add skills/yt-extract/SKILL.md
git commit -m "docs(skill): transcript-only save, frontmatter & What-next (Step 3)"
```

---

## Group C — No-URL handling, text Rückfrage (skills/yt-extract/SKILL.md)

### Task C1: No-URL guard with text Rückfrage (no AskUserQuestion)

**Files:** Modify `skills/yt-extract/SKILL.md` (END of Step 0.4 — after both URL *and* flag parsing, around line 142)

**Design:** Whenever the skill is reached with no URL and not `--check`, it must respond — never silently do nothing. The response is **plain text** (never `AskUserQuestion`), so it is safe in programmatic skill-to-skill calls where no human can answer. Two cases:
- No URL **and no flags** → full guided help (show all options).
- No URL **but flags were passed** (e.g. `/yt-extract --transcript-only`) → short Rückfrage that echoes the parsed flags and asks for a URL — do **not** re-dump the option list the user already chose from.

The guard must sit at the END of Step 0.4 (it needs to know whether flags were parsed), not before flag parsing.

- [ ] **Step 1: Add the no-URL guard at the end of Step 0.4**

````markdown
**No URL provided (always handled — never silently exit):** If, after parsing, **zero** YouTube URLs were found AND `--check` was not passed, do NOT dispatch. Respond with a plain-text message and stop. Never use `AskUserQuestion` here — a text reply is safe even when another skill invoked this one programmatically with no human present.

- **No flags either** → print the full guided help:

```
yt-extract — pull transcript, summary, metadata, screenshots & comments from a YouTube video.

Usage:  /yt-extract <youtube-url> [url2 url3] [flags]

Default (no flags):   structured summary + metadata, auto-saved as a Markdown file.

Optional flags:
  --transcript-only    just the raw transcript — fast, no summary or extras
  --full-transcript    raw transcript instead of a summary (keeps metadata)
  --comments           add the top 10 comments
  --screenshots        capture frames at chapter markers (needs ffmpeg)
  --no-save            show in chat only; ask before writing a file
  --check              verify dependencies only

Paste a URL to start. After the first run I'll suggest follow-ups you can chain
(summarize, extract tools, translate, compare videos) without re-fetching.
```

- **Flags were passed but no URL** → short Rückfrage that preserves the chosen flags (substitute the actual flags seen, e.g. `--transcript-only`):

```
Got --transcript-only, but no YouTube URL.
Paste one and I'll run with that:  /yt-extract <url> --transcript-only
```

No `AskUserQuestion`, no step-by-step wizard: the happy path (`/yt-extract <url>`) stays friction-free, and option discovery happens through the post-run "What next?" block. The conversational "you mentioned a video but no URL — which one?" behavior (preserving options the user described in natural language) is orchestrator behavior performed *before* the skill is invoked — see "Resolved decision" above — not part of this guard.
````

- [ ] **Step 2: Commit**

```bash
git add skills/yt-extract/SKILL.md
git commit -m "feat(skill): always answer no-URL invocation with a text Rueckfrage (Step 0.4)"
```

---

## Group D — Contract docs, version, quality gate & release

### Task D1: Update `CLAUDE.md` (skill↔script contract)

**Files:** Modify `CLAUDE.md`

- [ ] **Step 1: Document the flag in the "Script CLI" section**

In the "User-facing flags" paragraph of the "Script CLI (internal, skill-facing)" section, add `--transcript-only` to the list of skill-parsed flags, and add a row to the flag intent. Concretely, append to the user-facing-flags sentence:

```markdown
`--transcript-only` (raw transcript only, runs the script directly with `--transcript-only`, no subagent)
```

- [ ] **Step 2: Bump the version line**

Change `Current version: **1.6.0**` → `Current version: **1.7.0**` in the Components section.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document --transcript-only in CLAUDE.md contract"
```

---

### Task D2: Update `README.md`

**Files:** Modify `README.md`

- [ ] **Step 1: Add a Features bullet** (after the `--full-transcript` bullet, ~line 37)

```markdown
- ⚡ **Transcript-only** — Just the raw transcript, fast, no summary or extras (opt-in via `--transcript-only`); runs without a subagent
```

- [ ] **Step 2: Add the flag to the Usage & Flags table** (after the `--full-transcript` row, ~line 95)

```markdown
| `--transcript-only` | Output only the raw transcript — no metadata, summary, comments, or screenshots; no subagent. Folder/file named by video ID. |
```

- [ ] **Step 3: Add an example** (in the Examples block, ~line 116)

```markdown
# Just the raw transcript, fast — no summary, no metadata fetch
/yt-extract https://youtu.be/abc123 --transcript-only
```

- [ ] **Step 4: Bump version references** — badge (line ~12), Components table (line ~30), footer (line ~513): `1.6.0` → `1.7.0`.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs(readme): document --transcript-only + bump to 1.7.0"
```

---

### Task D3: Bump version in plugin manifests

**Files:** Modify `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`

- [ ] **Step 1: Update both version fields** `1.6.0` → `1.7.0`. (Read each file first to find the exact `"version"` key; change only that.)

- [ ] **Step 2: Commit**

```bash
git add .claude-plugin/plugin.json .claude-plugin/marketplace.json
git commit -m "chore: bump plugin version to 1.7.0"
```

---

### Task D4: Write the CHANGELOG entry

**Files:** Modify `CHANGELOG.md` (insert above the `## [1.6.0]` heading, ~line 7)

- [ ] **Step 1: Add the `[1.7.0]` section**

```markdown
## [1.7.0] — 2026-06-12

New lean `--transcript-only` mode: fetch and output just the raw transcript, no
metadata/description/chapters/comments/screenshots and no summary. It runs the
Python script **directly** (no subagent) because a subagent would only relay the
raw transcript back into context, paying its token cost twice. It also skips the
heavy `yt-dlp --dump-json` metadata call entirely, deriving the output folder
name from the video ID parsed out of the URL. Plus a guided help message when
`/yt-extract` is invoked without a URL.

### yt-extract.py (backend)

#### Added
- `extract_video_id(url)` — parses the 11-char YouTube video ID from `watch?v=`,
  `youtu.be/`, `/shorts/`, and `/embed/` URL forms; returns `None` on no match.
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
- No-URL handling: when `/yt-extract` is reached with no URL (and without
  `--check`), it always answers with a plain-text message instead of failing —
  the full guided help when no flags were given, or a short "paste a URL"
  Rückfrage that preserves already-chosen flags. Never an `AskUserQuestion`, so
  it is safe in programmatic skill-to-skill calls.

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
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): add 1.7.0 entry"
```

---

### Task D5: Quality gate — tests, review, simplify

- [ ] **Step 1: Run the full unit suite**

Run: `python -m pytest tests/ -v`
Expected: all pass (existing + 5 new `extract_video_id` cases), in well under a second.

- [ ] **Step 2: Review the SKILL.md changes**

Use the `/buzzwoo-standard:review-skill` command (dispatches component-reviewer-clara) on `skills/yt-extract/SKILL.md`, OR run `/code-review` on the working diff. Address any high-confidence findings.

- [ ] **Step 3: Simplify**

Run `/simplify` on the diff (reuse/consistency/altitude only — not a bug hunt). Apply suggested cleanups that don't change behavior. Re-run `python -m pytest tests/ -v` afterward to confirm green.

- [ ] **Step 4: Commit any review/simplify fixes**

```bash
git add -A
git commit -m "refactor: apply review + simplify feedback for transcript-only mode"
```

---

### Task D6: Manual integration verification (network required)

Per `CLAUDE.md`, subprocess/network paths are verified manually. Use a short, public, captioned video.

- [ ] **Step 1: Single URL, raw transcript**

Run:
```bash
python scripts/yt-extract.py "https://www.youtube.com/watch?v=<REAL_ID>" --transcript-only --output-base .
```
Expected: stdout shows `### Transcript Info` + `### Transcript` + a trailing `OUTPUT_FOLDER: ./yt-extract_<DATE>_<REAL_ID>` line; stderr shows `[1/2]` and `[2/2]`; a folder `yt-extract_<DATE>_<REAL_ID>/` is created. **No** metadata/comments/screenshots sections appear.

- [ ] **Step 2: Re-run without `--force` → collision guard**

Run the same command again.
Expected: exit code 2, stderr `FOLDER_EXISTS: ...`, no stdout sections.

- [ ] **Step 3: Skill end-to-end (in Claude Code)**

Install the plugin locally and run:
- `/yt-extract <real-url> --transcript-only` → chat shows the raw transcript with the video-ID note; a `.md` is saved; the What-next block offers "Summarize it".
- `/yt-extract <real-url> --transcript-only --no-save` → transcript in chat; asks before saving; on "no" the folder is removed.
- `/yt-extract <urlA> <urlB> --transcript-only` → two transcript sections, no synthesis.
- `/yt-extract` (no URL) → guided help message, no error, no dispatch.

- [ ] **Step 4: Clean up verification artifacts**

Remove the throwaway `yt-extract_<DATE>_*` folders created during manual testing (per the user's "delete throwaway verification artifacts" rule). Do **not** commit them.

---

### Task D7: Release (ASK before any remote action)

> Per the user's global rule: **never push, tag, or publish a release without explicit approval.** This task stops for confirmation.

- [ ] **Step 1: Confirm the branch & clean tree**

```bash
git status
git log --oneline -12
```
Expected: all Group A–D commits present, working tree clean.

- [ ] **Step 2: ASK the user** — "All changes committed on `main`, tests green, docs + CHANGELOG + version bumped to 1.7.0. Push to origin, tag `v1.7.0`, and publish the GitHub Release?" Wait for explicit yes.

- [ ] **Step 3: On approval only** — push, tag, and release (mirror the v1.6.0 process):

```bash
git push origin main
git tag v1.7.0
git push origin v1.7.0
gh release create v1.7.0 --title "v1.7.0 — transcript-only mode + guided help" --notes-file <(sed -n '/## \[1.7.0\]/,/## \[1.6.0\]/p' CHANGELOG.md | sed '$d')
```

- [ ] **Step 4: Optional smoke test** — `/plugin update` then `/yt-extract --check`.

---

## Self-Review (completed during planning)

**Spec coverage:**
- `--transcript-only` raw output → Tasks A1, A2, B1–B4. ✅
- Skip metadata / video-ID filename + user hint → A2 (`run_transcript_only`), B3 note line. ✅
- No subagent (avoid token doubling) → B2. ✅
- "Summarize via LLM" as follow-up, not a mode → B4 What-next variant. ✅
- Guided UX on bare invocation, flags preserved for programmatic use → C1 (help guard); flags untouched in A2/B1. ✅
- Review / test / simplify / README / CHANGELOG / version / release → D1–D7. ✅

**Placeholder scan:** No "TBD"/"handle edge cases"/"similar to" — every code and Markdown block is complete. ✅

**Type/name consistency:** `extract_video_id` (A1) is called in `run_transcript_only` (A2) and tested in A1 under the same name. `run_transcript_only(args)` matches the `main()` call site. `--transcript-only` → `args.transcript_only` (argparse dash→underscore) used consistently. The `FOLDER_EXISTS` / `OUTPUT_FOLDER` strings match the existing contract. ✅

**Scope check:** Two cohesive feature groups (transcript-only mode; bare-invocation help) shipping in one release; both touch the same SKILL.md regions and one CHANGELOG entry. Kept as one plan. If you prefer, Group C (UX) can be split into its own release after Groups A–B — they are independent.
```
