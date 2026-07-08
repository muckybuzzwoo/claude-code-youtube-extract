---
name: yt-extract
description: "Extract and analyze YouTube videos — transcript, metadata, screenshots, comments. Use only when explicitly asked to extract or analyze specific YouTube URL(s) — via /yt-extract or invoked programmatically from another skill via the Skill tool. Do not auto-trigger on incidental YouTube URL mentions or links shared merely as references."
user-invocable: true
argument-hint: "<youtube-url> [url2] [url3] [--screenshots [chapters|scenes[=t]|timestamps]] [--comments] [--full-transcript] [--no-save] | --check [--screenshots]"
allowed-tools: "Bash, Agent, Write, Read, AskUserQuestion"
---

Analyze the YouTube URL(s) from: <user_request>$ARGUMENTS</user_request>

## Step 0 — Preparation

### 0.1 Detect the host OS

Determine the OS from the active environment / system prompt — you do not need to run a command. Store the value as `<OS>` and use it to resolve every OS-specific lookup below.

**Python launcher** by OS (used anywhere the skill or a subagent invokes Python — substitute `<PY>` before execution):

| OS       | `<PY>`    |
|----------|-----------|
| Windows  | `python`  |
| macOS    | `python3` |
| Linux    | `python3` |

If OS detection fails, default to `<PY> = python3` (POSIX fallback). Never execute a command or dispatch a subagent prompt that still contains a literal `<PY>` token.

### 0.2 Dependency install matrix

The skill offers install-on-demand for both dependencies. Each dependency has a per-OS list of valid install commands. When the list has **multiple** entries, the skill asks the user which to run. When the list has **one** entry, it runs that command directly (still behind a confirmation prompt).

**Each entry has two forms:**
- **label** — short, user-friendly string shown in the `AskUserQuestion` dialog (e.g., `winget`, `pip`, `apt`).
- **command** — the exact non-interactive command line the skill executes via Bash. These commands are crafted to never block on a license prompt, a confirmation prompt, or a sudo password prompt under the Claude Code Bash tool, which has no stdin channel.

**yt-dlp install options:**

| OS       | Options (label → exact executed command)                                                                                               |
|----------|----------------------------------------------------------------------------------------------------------------------------------------|
| Windows  | `pip` → `pip install yt-dlp` **or** `winget` → `winget install yt-dlp --accept-package-agreements --accept-source-agreements --silent --disable-interactivity`  (→ **ask user**) |
| macOS    | `brew` → `brew install yt-dlp` **or** `pip3` → `pip3 install --user yt-dlp`  (→ **ask user**)                                          |
| Linux    | `pip` → `pip install --user yt-dlp` **or** `pipx` → `pipx install yt-dlp`  (→ **ask user**)                                            |

**ffmpeg install options:**

| OS       | Options (label → exact executed command)                                                                                               |
|----------|----------------------------------------------------------------------------------------------------------------------------------------|
| Windows  | `winget` → `winget install Gyan.FFmpeg --accept-package-agreements --accept-source-agreements --silent --disable-interactivity`        |
| macOS    | `brew` → `brew install ffmpeg`                                                                                                         |
| Linux    | auto-detect pkg-mgr (see note below), OR abort with manual-install instruction if `sudo` would prompt                                  |

**Linux ffmpeg — sudo handling (important):** `apt` and `dnf` both require root. Before attempting to run the install command, the helper probes `sudo -n true 2>/dev/null`. If that succeeds (active sudo session or passwordless sudo), the helper runs `sudo apt install -y ffmpeg` or `sudo dnf install -y ffmpeg`. If `sudo -n true` fails, the helper **does not execute** the install (it would hang on the password prompt). Instead it aborts with an English error message that shows the exact manual command for the user to run in their own terminal, plus the ffmpeg doc URL. If neither `apt` nor `dnf` is present, abort with doc link regardless of sudo state.

**Why these exact flags:**
- `--accept-package-agreements` / `--accept-source-agreements` (winget): auto-accept the third-party package and winget-source license terms. Without these flags, winget opens an interactive `y/n` prompt on first install of each source — which blocks the Bash tool indefinitely.
- `--silent` / `--disable-interactivity` (winget): suppresses the installer UI and aborts if any remaining interactive prompt appears, so the skill fails fast instead of hanging.
- `--user` (Linux `pip`, macOS `pip3`): installs into the user-scope site-packages directory — avoids needing root on Linux and sidesteps the system-Python `externally-managed-environment` block on macOS (PEP 668).
- `-y` (apt/dnf): auto-confirms the package install. Not sufficient by itself on Linux because `sudo` is still outside this scope — hence the `sudo -n` probe.

**Official doc URLs (used in error messages):**
- yt-dlp: `https://github.com/yt-dlp/yt-dlp/wiki/Installation`
- ffmpeg: `https://ffmpeg.org/download.html`

### 0.3 Check Python runtime and yt-dlp (always)

**0.3.a — Python runtime.** The subagents invoke the Python script via `<PY>`. If Python is missing, the subagent's first command will fail — and on macOS without Xcode Command Line Tools, `/usr/bin/python3` is a GUI stub that triggers an installer dialog on first call, which blocks the Bash tool indefinitely (no stdin, no way to accept). Verify Python upfront (substitute `<PY>` from the Step 0.1 table before running):

```bash
<PY> --version 2>&1
```

**If Python is present** (stdout matches `Python 3.X.Y` with X >= 9): continue to 0.3.b.

**If Python is missing or the command triggers an install-tool dialog** (macOS CLT prompt, `command not found`, or any non-zero exit): abort with the OS-specific message below. Do NOT retry and do NOT fall through to later steps — the subagent dispatch would fail.

- **Windows:**
  ```
  Python 3 is not installed.

  Install it from https://www.python.org/downloads/ (check "Add Python to PATH" in the installer), or run:
    winget install Python.Python.3.12 --silent --disable-interactivity --accept-package-agreements --accept-source-agreements

  Then restart your terminal and re-run /yt-extract.
  ```
- **macOS:**
  ```
  Python 3 is not installed (or Xcode Command Line Tools are missing).

  Install the Command Line Tools by running in your own terminal:
    xcode-select --install    (opens a GUI dialog — accept it)

  Or install via Homebrew:
    brew install python@3.12

  Then re-run /yt-extract.
  ```
- **Linux:**
  ```
  Python 3 is not installed.

  Install it via your package manager, e.g.:
    sudo apt install -y python3    (Debian/Ubuntu)
    sudo dnf install -y python3    (Fedora/RHEL)

  Then re-run /yt-extract.
  ```

**Abort the skill** after emitting the message. There is no automatic install path for Python — the CLT GUI dialog on macOS cannot be accepted non-interactively, and Python itself is a prerequisite the user must install once.

**0.3.b — yt-dlp.** Run:
```bash
yt-dlp --version 2>&1
```

**If yt-dlp is present:** continue to 0.4.

**If yt-dlp is missing AND `<OS> == Windows`:** before falling through to the install-helper's Steps A0-F, jump directly to **Step W (Windows PATH Recovery)** in `references/install-helper.md` with `dep_name = "yt-dlp"` and `verify_cmd = "yt-dlp --version"`. Dispatch on the return state:

- `recovered` → continue to 0.4 (skip the install-helper entirely — recovers the case where yt-dlp is already installed via winget but Bash cannot see it).
- `staged_for_restart` → emit Step W's restart message and abort the skill.
- `not_found` or `copy_failed` → fall through to the install-helper invocation below.

**If yt-dlp is missing (after the Windows pre-check, or on non-Windows):** invoke the **install-dependency helper** (see 0.6) with:
- `dep_name = "yt-dlp"`
- `options = yt-dlp install options for <OS>`
- `doc_url = "https://github.com/yt-dlp/yt-dlp/wiki/Installation"`
- `on_decline = "abort"`
- `verify_cmd = "yt-dlp --version"`

If the helper aborts, stop processing. If it succeeds, continue.

### 0.4 Parse URLs and flags

**Parse URLs:**
Split $ARGUMENTS on whitespace/newlines. Keep only strings starting with `https://www.youtube.com/`, `https://youtube.com/`, `https://m.youtube.com/`, or `https://youtu.be/`. Take at most the first 3 URLs. If more than 3 were found, show: "Only the first 3 URLs will be processed."

**Parse flags:**
- `--comments` → fetch top comments (slow, therefore optional)
- `--full-transcript` → return the raw transcript instead of a summary
- `--screenshots` → extract screenshots at scene changes via ffmpeg scene detection (default since v1.8.0 — works without chapter markers; requires ffmpeg)
- `--screenshots scenes=0.05` → scene detection with a custom threshold (default 0.04; higher = fewer captures)
- `--screenshots chapters` → extract screenshots at chapter markers (pre-1.8.0 default behavior)
- `--screenshots 0:30,2:15,5:00` → extract screenshots at specific timestamps
- `--no-save` → disable auto-save (default: analysis is auto-saved as an MD file)
- `--check` → verify dependencies only, no extraction. Runs Step 0 (Python runtime check, yt-dlp check, and ffmpeg check when combined with `--screenshots`), prints a readiness report, and stops. URLs are ignored in check mode.
- `--transcript-only` → fetch and output ONLY the raw transcript: no metadata, description, chapters, comments, screenshots, or LLM summary, and **no subagent** (the skill runs the script directly). When set, `--comments`, `--screenshots`, and `--full-transcript` are ignored — transcript-only is the leanest mode. Combinable with `--no-save`.

### 0.4.a No URL provided — always respond (never silently exit)

If, after parsing URLs and flags above, **zero** YouTube URLs were found AND `--check` was not passed, do NOT proceed to Step 0.5 or Step 1. Respond with a plain-text message and stop. **Never use `AskUserQuestion` here** — a text reply is safe even when another skill invoked this one programmatically with no human present.

- **No flags either** → print the full guided help:

```
yt-extract — pull transcript, summary, metadata, screenshots & comments from a YouTube video.

Usage:  /yt-extract <youtube-url> [url2 url3] [flags]

Default (no flags):   structured summary + metadata, auto-saved as a Markdown file.

Optional flags:
  --transcript-only    just the raw transcript — fast, no summary or extras
  --full-transcript    raw transcript instead of a summary (keeps metadata)
  --comments           add the top 10 comments
  --screenshots        capture frames at scene changes — great for tutorials
                       (needs ffmpeg); `--screenshots chapters` for chapter-aligned
  --no-save            show in chat only; ask before writing a file
  --check              verify dependencies only

Paste a URL to start. After the first run I'll suggest follow-ups you can chain
(summarize, extract tools, translate, compare videos) without re-fetching.
```

- **Flags were passed but no URL** → short Rückfrage that preserves the chosen flags (substitute the actual flags seen, e.g. `--transcript-only`):

```
Got [the flags you passed, e.g. --transcript-only], but no YouTube URL.
Paste one and I'll run with that:  /yt-extract <url> [those flags]
```

No `AskUserQuestion`, no step-by-step wizard: the happy path (`/yt-extract <url>`) stays friction-free, and option discovery happens through the post-run "What next?" block. The conversational "you mentioned a video but no URL — which one?" behavior (preserving options the user described in natural language) is orchestrator behavior performed *before* the skill is invoked, not part of this guard.

### 0.5 Check ffmpeg (only when `--screenshots` is set)

If `--screenshots` was **not** parsed, skip this step entirely.

**Narration:** Before running the check, say in chat: "Verifying ffmpeg before screenshot extraction..." — so the user sees what is happening.

Otherwise, run:
```bash
ffmpeg -version 2>&1
```

**If ffmpeg is present:** continue to Step 1.

**If ffmpeg is missing AND `<OS> == Windows`:** before falling through to the install-helper's Steps A0-F, jump directly to **Step W (Windows PATH Recovery)** in `references/install-helper.md` with `dep_name = "ffmpeg"` and `verify_cmd = "ffmpeg -version"`. Dispatch on the return state:

- `recovered` → continue to Step 1 (skip the install-helper entirely; both `ffmpeg.exe` and `ffprobe.exe` are recovered together).
- `staged_for_restart` → emit Step W's restart message and abort the skill (no `skip_screenshots` fallback in this branch — a half-installed dep is broken, matching Step E semantics).
- `not_found` or `copy_failed` → fall through to the install-helper invocation below.

**If ffmpeg is missing (after the Windows pre-check, or on non-Windows):** invoke the install-dependency helper (see 0.6) with:
- `dep_name = "ffmpeg"`
- `options = ffmpeg install options for <OS>`
- `doc_url = "https://ffmpeg.org/download.html"`
- `on_decline = "skip_screenshots"` (set an internal `skip_screenshots = true` flag and continue; do NOT abort)
- `verify_cmd = "ffmpeg -version"`

When `skip_screenshots` is set, **omit the `--screenshots` flag from the subagent's script invocation** and make a note in the final output that screenshots were skipped because ffmpeg was not installed.

This Step-0 check replaces the per-subagent `FFMPEG_MISSING` handling. It also prevents parallel install prompts on multi-URL runs — exactly **one** ffmpeg prompt fires before subagent dispatch, regardless of URL count.

### 0.6 Install-dependency helper (shared flow)

When Step 0.3.b or Step 0.5 needs to install a missing dependency, load and follow **`references/install-helper.md`** (inside this skill directory). That file documents the full flow as Steps A0 through F, including pre-flight checks (macOS brew availability, Linux sudo availability), the AskUserQuestion dialog, install execution, verification, and all error paths.

Inputs passed to the helper (same shape as documented there):
- `dep_name` — display name (e.g. `"yt-dlp"` or `"ffmpeg"`)
- `options` — ordered list of `{label, command}` pairs from the 0.2 matrix for the detected OS
- `doc_url` — official-docs link for manual install instructions
- `on_decline` — `"abort"` (yt-dlp) or `"skip_screenshots"` (ffmpeg)
- `verify_cmd` — command that must exit 0 after a successful install

The helper returns control after a successful install, or aborts the skill on a hard failure. Per-dep return semantics are documented in the reference file.

### 0.7 Short-circuit when `--check` is set

If the `--check` flag was parsed, print a readiness report and **stop**. Do NOT proceed to Step 1 or dispatch any subagents. Ignore any URLs the user passed.

Capture the current tool versions (substitute `<PY>` from Step 0.1 before running):

```bash
<PY> --version
yt-dlp --version
```

If `--screenshots` was also set, also capture:

```bash
ffmpeg -version 2>&1 | head -1
```

Then output:

```
Dependencies ready:
  - Python: [python version string]
  - yt-dlp: [yt-dlp version string]
  - ffmpeg: [ffmpeg first line — only if --screenshots was set; omit otherwise]

Ready to extract. Run `/yt-extract <url>` to analyze a video.
```

**Stop here.** `--check` is for verifying install only — it does not produce a Markdown file, does not fetch any video data, and does not dispatch subagents.

---

## Step 1 — Dispatch subagents

**IMPORTANT: Use the Agent tool with `subagent_type: "yt-extract:extract-worker"` and `model: "sonnet"` for each URL. With 2-3 URLs, dispatch all in parallel (in a single message with multiple Agent-tool calls).**

`extract-worker` is a restricted leaf worker that ships with this plugin (`agents/extract-worker.md`): its `tools` allowlist grants only `Bash, Read, Glob, Grep`, so it has **no `Skill` tool and no `Agent` tool** and therefore cannot re-invoke `/yt-extract` or spawn further subagents. **Do NOT dispatch `general-purpose` here** — that is exactly what caused the recursive-subagent loop fixed in 1.8.1 (a `general-purpose` worker re-triggered this skill, which dispatched another worker, ad infinitum). If `yt-extract:extract-worker` does not resolve, the plugin was not reloaded after install — surface that rather than falling back to `general-purpose`.

### Narration before dispatch

Before the Agent-tool call(s), say in chat what is about to happen. One short line is enough — the user has no other signal that work has started.

- **1 URL:** `Extracting from <shortened URL or known title>. This typically takes 30–60 seconds...`
- **2-3 URLs:** `Dispatching <N> parallel extractions...`

As each subagent returns, announce its result on one line (`URL <i>/<N> done: <OUTPUT_FOLDER>` or similar). This, combined with the `[k/N]` stage markers the Python script emits on stderr, gives the user continuous feedback even when an individual run runs long.

### `--output-base` resolution

Every subagent invocation must include `--output-base <path>`. The value depends on URL count:

- **1 URL:** `--output-base "."` — script creates `./yt-extract_[DATE]_[slug]/` directly in CWD.
- **2-3 URLs:** `--output-base "./yt-extract_[DATE]_[N]-videos"` — **before** dispatching subagents, create this parent folder with `mkdir -p`. Each subagent's script then writes into `./yt-extract_[DATE]_[N]-videos/yt-extract_[DATE]_[slug]/`.

When the parent folder (multi-URL case) already exists, ask the user via AskUserQuestion "Folder `<path>` already exists. Overwrite?" **before** creating it. On "yes": remove the existing folder (`rm -rf`) and re-create, then dispatch subagents **with `--force`** appended to each script invocation so per-video collisions inside the parent are also overwritten silently. On "no": abort the skill with a short message.

### Handling worker-returned states — YOU (the orchestrator) ask the user, not the worker

The `extract-worker` subagent has **no `AskUserQuestion` tool** (no subagent does — it depends on the main-chat UI). So any state that needs a user decision is **returned by the worker** and resolved **here, in the main context, by you**, then the worker is re-dispatched. Two such states:

**FOLDER_EXISTS:** If a worker's returned output is (or contains) a line `FOLDER_EXISTS: <path>`, the per-video target folder already exists from a previous run. Ask the user via AskUserQuestion: `Folder "<path>" already exists. Overwrite?` with options "Yes, overwrite" and "No, abort". On **Yes**: re-dispatch the *same* worker prompt for that URL with `--force` appended to the script command. On **No**: treat that URL as a failed/skipped extraction (note it; for a single URL, stop with a short message). (In multi-URL runs this rarely fires: the parent-folder overwrite above already passes `--force` to every worker, so per-video collisions are pre-resolved.)

**SCREENSHOTS_ASK_USER:** If a worker's returned output has `SCREENSHOTS_ASK_USER` in its `### Screenshots` section (only `--screenshots chapters` on a chapterless video produces it — scene mode never does), ask the user via AskUserQuestion: "This video has no chapter markers. How should screenshots be taken?" with options A) "Evenly distributed (1 per 2 min, max 10)" B) "Enter manual timestamps". On **A**: compute timestamps from the `video_duration` value in that `### Screenshots` section, build a comma-separated list, and re-dispatch the worker with `--screenshots T1,T2,T3,... --force` (the first run already created the folder). On **B**: collect the user's timestamps, then re-dispatch with `--screenshots <those> --force`. Either way, **discard the first worker output entirely** and use the re-dispatched run's output.

Re-dispatching a worker is a normal Agent-tool call from the main context — it is not recursion (the worker still has no `Skill`/`Agent` tool and runs exactly one command).

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

**Stage markers:** the script emits `[1/2] Downloading transcript` and `[2/2] Writing output` on stderr (N is always 2 in this mode) — surface each as a one-line update.

**FOLDER_EXISTS (exit code 2):** identical handling to the other modes — if a Bash call exits 2 with `FOLDER_EXISTS: <path>` on stderr, ask via AskUserQuestion ("Folder already exists. Overwrite?") and re-run that exact command with `--force` appended.

**Parse `OUTPUT_FOLDER: <path>`** (extract the path as described in Step 3's `OUTPUT_FOLDER` rule — transcript-only runs in the main context with no subagent boundary, so there is no `agentId:` trailer here, but use the same extraction) to locate each target folder. Trim it from the transcript text before formatting. Then treat each script's stdout exactly as you would a subagent's returned output: format per Step 2's "Transcript-only output", then run Step 3's saving flow on it. **Step 3 applies even though no subagent ran** — including `--no-save`: the script has already created the target folder, so if `--no-save` was set, ask before writing the `.md` and on decline `rm -rf` the folder(s), exactly as in the other modes.

---

### When --full-transcript is NOT set (default):

Each subagent gets this prompt (substitute URL, flags, and `--output-base` path per Step 1 resolution rules above):

---

You are a LEAF worker. Run ONLY the single Bash command below and then format its output. Do NOT invoke any skill — especially NOT `/yt-extract` — and do NOT dispatch any subagent. (The `extract-worker` agent has neither the `Skill` nor the `Agent` tool; if you ever feel an urge to delegate, run the command yourself instead.)

Extract all data for this YouTube video and summarize the transcript.

1. Run:
```bash
<PY> "${CLAUDE_PLUGIN_ROOT}/scripts/yt-extract.py" "[URL]" --output-base "[OUTPUT_BASE]" [--force if the orchestrator said so] [--comments if requested] [--screenshots if requested — pass the user's value verbatim: nothing | scenes=T | chapters | timestamps]
```

**Progress surfacing (stderr stage markers):** The Python script emits lines like `[1/5] Fetching metadata...`, `[2/5] Downloading transcript...`, `[3/6] Detecting scene changes` (scene mode only — this stage decodes the whole video and can take minutes on long videos), `[4/6] Extracting 7 screenshots...` on stderr, flushed immediately. When each stage completes, surface the marker as a one-line update in your returned message so the user sees forward motion during long runs.

**FOLDER_EXISTS handling (exit code 2):** If the Bash command exits with code 2 AND stderr contains `FOLDER_EXISTS: <path>`, the target folder already exists. **Do NOT retry and do NOT ask the user — you have no `AskUserQuestion` tool.** Return exactly the single line `FOLDER_EXISTS: <path>` (verbatim, the path from stderr) as your entire response and stop. The orchestrator runs in the main chat, will ask the user, and will re-dispatch you with `--force` if the user confirms.

2. **Check the `### Screenshots` section for `SCREENSHOTS_ASK_USER`:**
   - Only `--screenshots chapters` on a video without chapter markers produces this sentinel — scene-detection mode (the default) never does.
   - If `SCREENSHOTS_ASK_USER` appears in the `### Screenshots` section: **Do NOT ask the user — you have no `AskUserQuestion` tool.** Return the script output unchanged (it includes the `### Screenshots` section with the `SCREENSHOTS_ASK_USER` marker and the `video_duration` value) and stop. The orchestrator will ask the user for a screenshot strategy and re-dispatch you with explicit timestamps + `--force`.
   - `FFMPEG_MISSING` should not appear at this stage — Step 0.5 already verified ffmpeg presence before dispatch. If it does appear (defense-in-depth), return it verbatim — do not try to resolve it; the orchestrator surfaces the Step E stale-PATH message from `references/install-helper.md`.

3. Return the **Metadata**, **Description**, **Chapters** (if present), and **Comments** sections UNCHANGED.

4. Return the **Screenshots** and **Screenshot Status** sections (if present) UNCHANGED — they contain relative image paths (like `screenshots/NNN_HHmmss.png`) and error/success messages that must be preserved.

**Preserve the trailing `OUTPUT_FOLDER: <path>` line** that the script emits after the Comments section. The orchestrator parses this to decide where to write the consolidated markdown. Return it verbatim at the end of your response.

5. Replace the raw transcript with a **STRUCTURED SUMMARY**:
   - Keep the **Transcript Info** (auto-generated/manual, language) as the first line
   - The Python script already emits canonical section order, screenshot filename conventions, timestamp formatting, screenshot status wording, and screenshot/transcript embedding structure. Preserve those deterministic parts exactly as emitted.
   - If no transcript is available: return only the note "No transcript available."
   - Build the summary with exactly this structure:

```
### Transcript Info
[auto-generated/manual, language — taken from the script output]

### Transcript Summary

#### Core Thesis
[1-2 sentences: What is the video about? What is the central claim?]

#### Main Points
[Numbered list of the most important arguments/insights, 1-2 sentences each. Cover all essential content — the goal is that the user should not need to watch the video again.]

#### Tools & Resources Mentioned
[All concrete tools, libraries, links, repos, products named in the video — with URL if included in transcript or description]

#### Key Quotes & Numbers
[Concrete metrics, statistics, verbatim statements that are particularly relevant or quotable]
```

   - Language of the summary = language of the transcript
   - DETAILED enough that watching the video again is unnecessary
   - If screenshots are embedded in the transcript (image references): REMOVE them from the summary — the Screenshots section shows them separately.

---

### When --full-transcript IS set:

Each subagent gets this prompt (substitute URL, flags, and `--output-base` path per Step 1 resolution rules above):

---

You are a LEAF worker. Run ONLY the single Bash command below and then return its output. Do NOT invoke any skill — especially NOT `/yt-extract` — and do NOT dispatch any subagent. (The `extract-worker` agent has neither the `Skill` nor the `Agent` tool; if you ever feel an urge to delegate, run the command yourself instead.)

Extract all data for this YouTube video. Return exclusively the output of the Python script — no additional explanation, no preamble, no wrapper.

Run exactly this one command:
```bash
<PY> "${CLAUDE_PLUGIN_ROOT}/scripts/yt-extract.py" "[URL]" --output-base "[OUTPUT_BASE]" [--force if the orchestrator said so] [--comments if requested] [--screenshots if requested — pass the user's value verbatim: nothing | scenes=T | chapters | timestamps]
```

**Progress surfacing:** The script emits `[k/N]` stage markers on stderr throughout the run (scene mode adds a `Detecting scene changes` stage that decodes the whole video and can take minutes). Surface each one as a one-line update so the user sees forward motion.

**FOLDER_EXISTS handling (exit code 2):** If the command exits with code 2 AND stderr contains `FOLDER_EXISTS: <path>`, **do NOT retry and do NOT ask — you have no `AskUserQuestion` tool.** Return exactly the single line `FOLDER_EXISTS: <path>` (verbatim) as your entire response and stop. The orchestrator will ask the user and re-dispatch you with `--force` if confirmed.

**Check the `### Screenshots` section for `SCREENSHOTS_ASK_USER`** (identical to summary mode — only `--screenshots chapters` on a chapterless video produces it, scene mode never does): **do NOT ask — you have no `AskUserQuestion` tool.** Return the script output unchanged (it carries the `SCREENSHOTS_ASK_USER` marker and the `video_duration`) and stop; the orchestrator asks the user for timestamps and re-dispatches you with `--screenshots <timestamps> --force`. `FFMPEG_MISSING` is handled in Step 0.5 before dispatch and should not appear here.

Return the complete script output as the answer — including the trailing `OUTPUT_FOLDER: <path>` line, which the orchestrator needs to locate the target folder. Add nothing, omit nothing. Screenshot image references inside the transcript and the `### Screenshot Status` section are preserved.

---

## Step 2 — Format and output the results

Once all subagents have finished, parse the markdown blocks from the results and format the output:

The Python backend is the source of truth for deterministic formatting. The skill should decide workflow, ask user questions, dispatch subagents, summarize transcript content, and assemble multi-video output. It should not reinvent low-level markdown conventions that the script already renders consistently.

### With exactly 1 URL:

```
## [Title]
**Channel:** [Channel] | **Date:** [YYYY-MM-DD] | **Duration:** [HH:MM:SS] | **Views:** [n] | **Likes:** [n]

---

## Description
[from subagent — keep chapter markers and relevant links]

---

## Chapters
[If present: list of chapter markers with timestamps.]
[**Chapter-aligned screenshot embedding (SUMMARY MODE ONLY)**: If `--full-transcript` was NOT set AND `--screenshots` WAS set AND the number of screenshots equals the number of chapter markers AND each screenshot's timestamp matches a chapter timestamp → embed the screenshot IMMEDIATELY below its matching chapter line, indented with 2 spaces. Format:]

```
- [0:00] Intro

  ![Intro](screenshots/001_00m00s_intro.png)

- [2:15] Docker install

  ![Docker install](screenshots/002_02m15s_docker.png)
```

[**In `--full-transcript` mode**: OMIT all images from this section — the transcript section below contains them as structured h3 blocks (heading + image + text). Render the Chapters section as a plain TOC of timestamps and titles only.]
[If chapters are not present: omit the section entirely.]

---

## Transcript Summary
[If auto-generated: > Note: Auto-generated subtitles ([language])]
[If livestream: > Note: Livestream recording]
[If no transcript: > No transcript available.]

[Structured summary: Core Thesis, Main Points, Tools & Resources, Quotes & Numbers]

> Tip: Full transcript available — re-run with `--full-transcript` if needed.

---

## Screenshots
[**Conditional rendering:**]
[• In `--full-transcript` mode with chapter-aligned screenshots: OMIT — already embedded as h3 blocks inside `## Transcript`.]
[• In `--full-transcript` mode with custom-timestamp screenshots: OMIT — already embedded with h3 headings inside `## Transcript`.]
[• In summary mode with chapter-aligned screenshots: OMIT — already embedded under `## Chapters` above.]
[• In summary mode with NON-chapter-aligned screenshots (scene-detected — the default mode, custom timestamps, no chapters, or count mismatch): render the standalone list with image references and timestamps — from the subagent's `### Screenshots` section UNCHANGED. Scene-detected screenshots always take this path; chapter embedding only ever applies to `--screenshots chapters` runs.]
[• If `--screenshots` was requested but produced nothing: > No screenshots extracted.]
[• If `--screenshots` was not requested: omit the section.]

## Screenshot Status
[If present: success/error messages from subagent UNCHANGED — keep the `"N screenshots requested, M successfully extracted"` line even when the `## Screenshots` section above was suppressed due to chapter embedding. Scene mode may add `- WARNING:` lines (evenly thinned to 50, or no scene changes above threshold) — keep them unchanged too, they carry the re-run tuning hint.]
[If `--screenshots` was not requested: omit the section.]

---

## Top Comments
[If present: numbered list]
[If skipped: > Comments not requested. Enable with `--comments`.]
[If error: > Comments could not be loaded.]
```

**With --full-transcript:** the section is called `## Transcript`. When `--screenshots` is also set, the Python script pre-structures the transcript with `### [HH:MM] Chapter Title` h3 sub-headings (for chapter-aligned runs) or `### [HH:MM]` h3 sub-headings (for custom timestamps) — each heading is immediately followed by the matching screenshot and then the transcript text for that interval. Use the subagent's output verbatim; no further reformatting needed. No hint about --full-transcript needed.

### With 2 or 3 URLs:

```
# Analysis: [N] videos

---

## Video 1: [Title]
**Channel:** [Channel] | **Date:** [YYYY-MM-DD] | **Duration:** [HH:MM:SS] | **Views:** [n] | **Likes:** [n]

### Description
[from subagent]

### Chapters
[If present: apply the same chapter-aligned screenshot embedding rule as single-video mode — summary mode only: embed screenshots indented below each matching chapter line. In `--full-transcript` mode: render as plain TOC, the screenshots live in the Transcript section instead.]

### Transcript Summary
[Info + structured summary]

### Screenshots
[Apply the same conditional-rendering rule as single-video mode: omit if chapter-aligned (already embedded above); otherwise show the standalone list.]

### Screenshot Status
[If present: success/error messages — kept even when Screenshots section was suppressed due to chapter embedding]

### Top Comments
[List or hint]

---

## Video 2: [Title]
[same structure]

---

## Synthesis

**Shared themes:** [content that appears across multiple/all videos]

**Differences & contradictions:** [diverging approaches, conflicting statements]

**Overall key takeaways:** [the most important insights across all videos]

**Tools & resources mentioned:** [consolidated list of all links, tools, repos]
```

**With --full-transcript (multi-URL):** sections are called `### Transcript`. The subagent's transcript output already contains `### [HH:MM] ...` h3 sub-headings emitted by the Python script. To keep the heading hierarchy correct under the surrounding `### Transcript` heading, **apply a one-pass demote** on each subagent's transcript text before inserting it into the consolidated MD: replace every occurrence of `^### ` (start-of-line hash-hash-hash-space) with `#### `. This shifts the chapter sub-headings to h4 so they render as proper children of `### Transcript`.

---

### Transcript-only output (when `--transcript-only` is set):

The script emits only `### Transcript Info` and `### Transcript`. Derive `[video ID]` from the `OUTPUT_FOLDER` last path segment (the part after `yt-extract_<DATE>_`) — it is the video ID in the normal case, or a `video-<slug>` fallback when the ID could not be parsed from the URL. Format as:

**1 URL:**
```
## Transcript — [video ID]
> Note: transcript-only mode — output folder/file is named by the video ID (no metadata was fetched).
> [If auto-generated:] Note: Auto-generated subtitles ([language])

[raw transcript verbatim from the script's ### Transcript section]
```

**2-3 URLs:** one `## Transcript [i] — [video ID]` section per video, in input order. **No Synthesis section** — transcript-only is raw data, not cross-video analysis.

If a video has no transcript, render `> No transcript available.` for that video and continue.

---

## Step 3 — File saving

**Default behavior (auto-save):** The analysis is automatically saved as a Markdown file in its own folder. The output still appears in full in the chat.

**With `--no-save`:** The Python script still runs normally and creates the target folder (it has to — screenshots and the OUTPUT_FOLDER trailer depend on it). **Even in `--no-save` mode, parse the `OUTPUT_FOLDER:` trailer from each subagent's output** — it is required to locate the folder for cleanup on decline. After the chat output, ask: "Should I save the analysis as a Markdown file?" On "yes" → same flow as auto-save (including the follow-up invitation at the end). On "no" → **remove the folder(s) the script created** with `rm -rf <OUTPUT_FOLDER>` (for 1 video) or `rm -rf ./yt-extract_[DATE]_[N]-videos/` (for multi-video), then emit the follow-up invitation at the very end (with phrasing "The analysis is in context — you can ask me to:" since no file was saved).

### Folder structure

The Python script owns the per-video folder layout. The skill only orchestrates `--output-base` and, for multi-video runs, the parent folder + consolidated MD.

**For 1 video:**
```
./yt-extract_[YYYY-MM-DD]_[slug]/
  yt-extract_[YYYY-MM-DD]_[slug].md     ← written by the skill (from subagent output)
  screenshots/                          ← created by the script, only with --screenshots
    001_00m30s_intro.png
    002_02m15s_installing-docker.png
```

**For 2-3 videos:**
```
./yt-extract_[YYYY-MM-DD]_[N]-videos/
  yt-extract_[YYYY-MM-DD]_[N]-videos.md     ← written by the skill (consolidated)
  yt-extract_[YYYY-MM-DD]_[slug-video1]/    ← created by subagent 1's script
    screenshots/
      001_00m30s.png
  yt-extract_[YYYY-MM-DD]_[slug-video2]/    ← created by subagent 2's script
    screenshots/
      001_01m00s.png
```

- Slug: title lowercased, special chars removed, spaces → hyphens, max. 50 chars
- YYYY-MM-DD: today's date

### Auto-save flow

The Python script creates the per-video folder and any screenshots inside it directly — no staging, no moves. The skill's job is three things: pass the right `--output-base` on dispatch, read the `OUTPUT_FOLDER:` trailer from subagent output, and write the consolidated markdown.

1. **Read `OUTPUT_FOLDER: <path>` from each subagent's output.** The script prints it as the final stdout line, but **do not blindly take the last line.** When a subagent returns, the harness can append its own `agentId: <hex>` trailer onto that line with **no separating newline**, e.g. `OUTPUT_FOLDER: ./yt-extract_2026-06-13_my-slugagentId: a2ba5e8f`. To extract the folder reliably: take the text after `OUTPUT_FOLDER:`, then **cut it at the first whitespace and at the literal substring `agentId`, whichever comes first**, and strip surrounding whitespace. The result (`./yt-extract_2026-06-13_my-slug` in the example) is the folder path — forward slashes, relative to CWD, never containing a space or a colon. Trim the whole trailer line from the markdown before further processing — it is an orchestration marker, not analysis content.

2. **Prepend YAML frontmatter** (see below) to the markdown.

3. **Rewrite screenshot paths (multi-video only).** Per-video subagent output references screenshots as `screenshots/NNN_foo.png` (relative to the per-video folder). In the consolidated multi-video MD, rewrite each video's paths to `yt-extract_[DATE]_[slug]/screenshots/NNN_foo.png` (relative to the parent folder where the consolidated MD lives). Use the slug from that video's OUTPUT_FOLDER. Single-video mode needs no rewrite — paths already resolve correctly because the MD lives next to the `screenshots/` folder.

4. **Write the MD file** with the Write tool:
   - **1 video:** `<OUTPUT_FOLDER>/yt-extract_[DATE]_[slug].md` — derive the filename from the last path segment of OUTPUT_FOLDER.
   - **2-3 videos:** `./yt-extract_[DATE]_[N]-videos/yt-extract_[DATE]_[N]-videos.md`.

5. **Show confirmation in chat:**
   - With screenshots: `Saved: [folder]/[file].md ([N] screenshots)` — **take `[N]` from the `### Screenshot Status` line that the script already printed (format: "`N screenshots requested, M successfully extracted`" — use `M`, summed across all videos for multi-URL). Do NOT run a filesystem count to verify; the script is the source of truth.**
   - Without screenshots: `Saved: [folder]/[file].md`

6. **Follow-up invitation.** After the `Saved:` line (or directly after the content when `--no-save` was used and the user declined saving), emit one blank line, then a **"What next?"** block that invites follow-up queries.

    Exact structure:

    ```
    **What next?** The full analysis is in context — you can ask me to:
    - Extract all tools & resources as a bulleted checklist
    - Write a LinkedIn post / blog draft from the summary
    - [conditional 4th leverage bullet, see below]
    - Translate the summary to another language

    Or re-run with more data:
    - [conditional re-run bullets, see below]
    ```

    **Conditional 4th leverage bullet (chapter drill-down):**
    - If the current run rendered at least one `### Chapters` section: include `Drill into a specific chapter (e.g. "more on [HH:MM] Chapter Title")` — substitute `[HH:MM] Chapter Title` with an **actual** entry picked from the run's chapters (first video's chapters if multi-video).
    - Else if multi-video (2–3 URLs) with no chapters anywhere: include `Pick the best video for your specific use case from the synthesis`.
    - Else (single video, no chapters): omit this bullet entirely (block has 3 leverage bullets only).

    **Conditional re-run sub-block.** Include the `Or re-run with more data:` line AND the bullets below it ONLY when at least one of these conditions is true. Omit the whole sub-block otherwise.
    - `--comments` was NOT used → include `` `--comments` to add top viewer comments ``
    - `--full-transcript` was NOT used → include `` `--full-transcript` for raw text instead of summary ``
    - `--screenshots` was NOT used → include `` `--screenshots` for scene-change frame captures (`--screenshots chapters` for chapter-aligned) ``
    - Single URL (not multi-video) → include `Compare to related videos: /yt-extract <url1> <url2> [<url3>]`

    **Transcript-only variant of the What-next block.** When `--transcript-only` was used, replace the standard block above with this — the raw transcript is in context, so the summary becomes a follow-up rather than a separate mode:

    ```
    **What next?** The raw transcript is in context — you can ask me to:
    - Summarize it (Core Thesis, Main Points, Tools & Resources, Quotes & Numbers)
    - Extract all tools & resources as a checklist
    - Translate it to another language

    Or re-run for the full treatment:
    - Drop `--transcript-only` for metadata + a structured summary
    - Add `--comments` or `--screenshots` for viewer comments or chapter frames
    ```

    **Do NOT emit the follow-up invitation in these cases:**
    - `--check` mode (Step 0.7 short-circuit — it has its own "Ready to extract." message).
    - Any error path where the subagent failed or aborted before content was assembled (e.g. yt-dlp install declined, install-helper Step E stale-PATH abort). The block is contingent on a successful extraction with formatted content in the chat.

### YAML frontmatter

**For 1 video:**
```yaml
---
title: "[video title]"
channel: "[channel name]"
date: "[upload date YYYY-MM-DD]"
url: "[YouTube URL]"
analyzed: "[today's date YYYY-MM-DD]"
flags: [screenshots, comments]
---
```

**For 2-3 videos:**
```yaml
---
analyzed: "[today's date YYYY-MM-DD]"
flags: [screenshots, comments]
videos:
  - title: "[title video 1]"
    channel: "[channel 1]"
    date: "[date 1]"
    url: "[url 1]"
  - title: "[title video 2]"
    channel: "[channel 2]"
    date: "[date 2]"
    url: "[url 2]"
---
```

- `flags` contains only the flags actually used (empty array `[]` when none)
- All string values in YAML are quoted to handle special characters in titles
- **Transcript-only mode:** no metadata is fetched, so for the single-video frontmatter set `title: "[video ID]"` and omit `channel`/`date` (keep `url` and `analyzed`). `flags` includes `transcript-only`. The filename derives from the `OUTPUT_FOLDER` last path segment exactly as in the other modes.

---

## Edge cases

- **Video unavailable/private:** the section shows an error message; synthesis is based on available videos
- **No transcript:** "No transcript available" hint in the section, summary is omitted for that video, synthesis uses available transcripts
- **Live livestream:** "Ongoing livestream — transcript available only after it ends"; metadata is still shown
- **YouTube Short (< 3 min):** process normally, no length hint
- **Manual subtitles only:** use them (no "auto-generated" hint)
- **ffmpeg not installed:** handled in Step 0.5 before subagent dispatch (install-on-demand with per-OS command). `FFMPEG_MISSING` marker in the script output is defensive-only — normally unreachable.
- **--screenshots chapters without chapter markers:** `SCREENSHOTS_ASK_USER` marker → the worker returns it; the **orchestrator** asks the user for a strategy (evenly distributed or manual input) and re-dispatches with explicit timestamps (see "Handling worker-returned states" in Step 1). Only the explicit `chapters` mode produces this — bare `--screenshots` (scene detection) works without chapters.
- **Scene detection finds nothing above threshold:** the run still succeeds with the opening frame only; `### Screenshot Status` carries a WARNING suggesting a lower threshold (e.g. `scenes=0.01`).
- **Scene detection finds too many changes (>50 after the 4s min-gap):** evenly thinned to 50; WARNING in `### Screenshot Status` suggests a higher threshold (e.g. `scenes=0.05`).
- **Scene-detection pass runs long:** it decodes the whole video at low resolution — minutes on long videos. The `Detecting scene changes` stage marker covers the silence; the script enforces a duration-scaled timeout (max 30 min).
- **Scene-detection stream stall/timeout:** WARNING in `### Screenshot Status`, run completes with 0 screenshots — suggest re-running with `--screenshots chapters` or explicit timestamps. An HTTP 403 (transiently invalidated stream URL) is retried once automatically with a fresh URL before the script gives up.
- **Timestamp outside video duration:** skipped by the Python script with a WARNING, no interruption
- **Stream URL expired:** if ffmpeg reports a stale/expired stream URL (HTTP 403 or similar during screenshot extraction), re-run the script once — yt-dlp fetches a fresh URL on each invocation. Surface the retry to the user as a one-line status.
- **Target folder already exists:** script exits 2 with `FOLDER_EXISTS: <path>` on stderr → the worker returns the `FOLDER_EXISTS:` line; the **orchestrator** asks the user via AskUserQuestion and re-dispatches the worker with `--force` on confirmation (workers have no AskUserQuestion tool — see "Handling worker-returned states" in Step 1). Multi-URL parent-folder collisions are handled by the skill itself before dispatch (see Step 1). The `--transcript-only` path runs in the main context (no subagent), so it asks and re-runs inline.

---

## Extending this skill

Contributor reference. End-users never read this section.

- **Full conventions:** see `CLAUDE.md` at the repo root — it is the source of truth for the orchestration contract between this skill and `scripts/yt-extract.py`.
- **Adding a user-facing flag:** extend the parser in Step 0.4, wire its translation into the `--output-base`/script-flag block in Step 1 (both the summary-mode and `--full-transcript` subagent prompts), and document it in `README.md` and `argument-hint`.
- **Adding a new install target:** update the Step 0.2 matrix AND the matching matrix in `CLAUDE.md`. Every new command must be non-interactive (no license prompts, no sudo password prompts, no stdin reads) — the Bash tool has no stdin channel.
- **Adding a sentinel or orchestration trailer:** the current registry is `FFMPEG_MISSING`, `SCREENSHOTS_ASK_USER`, `FOLDER_EXISTS:` (stderr, exit 2), and `OUTPUT_FOLDER:` (trailing stdout). Adding a new one requires coordinated changes in the script, both subagent prompts (Step 1), the skill's post-processing (Step 2/3), and the `CLAUDE.md` registry. (v1.8.0 scene detection deliberately added none — overflow/zero-detection conditions travel as WARNING lines inside `### Screenshot Status`.)
- **Adding a Markdown section:** the script emits a fixed set of `###` headers parsed verbatim by the subagent prompts. Renaming or adding one requires changes on both sides — see the "Section headers" note in `CLAUDE.md`.
- **Releasing a version:** bump the version string in `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` (two entries — the marketplace and the plugin), `CLAUDE.md` (the "Current version" line), and `README.md` (the version badge, the two components-table rows, and the footer). Leave historical "Since x.y.z" references in `CLAUDE.md` and the tests untouched — they record when a feature landed, not the current version. Add a `## [x.y.z]` section at the top of `CHANGELOG.md` in [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format, versioned per [SemVer](https://semver.org/): patch for fixes/docs, minor for backward-compatible features, major (or a `!` on the commit type) for breaking changes. Run `python -m pytest tests/` and keep it green. Then commit, create an annotated tag `vX.Y.Z`, push both, publish the GitHub Release from the CHANGELOG block (`gh release create vX.Y.Z --latest`), and refresh the locally installed copy with `claude plugin update yt-extract@yt-extract` (the marketplace-qualified name is required).
- **Line-count budget:** this skill is intentionally long because it documents the full orchestration contract between the skill and `scripts/yt-extract.py`. The 500-line figure in the skills docs is a soft guideline, not a hard limit. The install-dependency helper already lives in `references/install-helper.md` — prefer extracting other long sub-workflows to `references/` rather than growing this file further.
