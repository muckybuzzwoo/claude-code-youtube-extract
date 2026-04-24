<p align="center">
  <img src="assets/claude-jumping.svg" alt="Jumping Claude mascot" width="140" height="126">
</p>

<h1 align="center">yt-extract</h1>

<p align="center">
  <em>Extract transcripts, metadata, screenshots, and comments from YouTube videos — all in one Claude Code command.</em>
</p>

<p align="center">
  <img alt="version" src="https://img.shields.io/badge/version-1.3.0-blue">
  <img alt="claude-code" src="https://img.shields.io/badge/Claude%20Code-plugin-purple">
  <img alt="license" src="https://img.shields.io/badge/license-Apache%202.0-green">
  <img alt="platform" src="https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey">
  <img alt="python" src="https://img.shields.io/badge/python-3.8%2B-yellow">
  <img alt="youtube" src="https://img.shields.io/badge/YouTube-FF0000?logo=youtube&logoColor=white">
</p>

## The Problem

Tutorial videos are trapped knowledge. The content is valuable, but it sits behind 30 minutes of playback — no searchable text, no copy-paste. You watch once, forget half, and can't easily cite or reuse what you heard.

`yt-extract` pulls the full value out of a YouTube video in one command: structured metadata, a filtered description, the complete transcript (summarized or raw), the top comments, and — if you want — screenshots at chapter markers. Everything lands in a dated folder as a single Markdown file you can search, cite, or feed back into Claude.

## Components

| Type  | Name         | Version | Description                                                                 |
|-------|--------------|---------|-----------------------------------------------------------------------------|
| Skill | `yt-extract` | 1.3.0   | Extract transcripts, metadata, screenshots, and comments from YouTube videos |

This plugin has no dependencies on other Claude Code plugins.

## Features

- 📝 **Structured summary** — Key thesis, main points, tools & resources, quotes & numbers
- 📄 **Full transcript** — Raw text with preserved chapter markers (opt-in via `--full-transcript`)
- 🏷️ **Metadata** — Title, channel, upload date, duration, view/like counts, chapters
- 🔎 **Filtered description** — Subscribe/social boilerplate stripped, tool links preserved
- 📸 **Screenshots** — Frames at chapter markers or custom timestamps, embedded in transcript (opt-in via `--screenshots`)
- 💬 **Comments** — Top 10 comments sorted by likes (opt-in via `--comments`)
- 🎞️ **Multi-video mode** — 2-3 URLs in one call, with a synthesis section across all videos
- 💾 **Auto-save** — Dated folder with Markdown file, YAML frontmatter, organized screenshots
- ⚡ **Parallel extraction** — Each URL runs in its own subagent, so 3 videos take the time of 1
- 🛠️ **Install-on-demand** — Missing `yt-dlp` or `ffmpeg`? The skill offers to install them for you, per-OS.

## Quick Start

### 1. Add the marketplace

```bash
/plugin marketplace add muckybuzzwoo/claude-code-youtube-extract
```

Or clone and add the local path:

```bash
git clone https://github.com/muckybuzzwoo/claude-code-youtube-extract.git
# then in Claude Code:
/plugin marketplace add /path/to/claude-code-youtube-extract
```

### 2. Install the plugin

```bash
/plugin install yt-extract
```

### 3. (Optional) Verify install

```bash
/yt-extract --check
```

This runs the dependency check (`yt-dlp`, plus `ffmpeg` if you add `--screenshots`) and triggers the install-on-demand flow when something is missing — without doing any video extraction. On Windows you may need to restart Claude Code once after a winget install (see [Troubleshooting](#troubleshooting)), then re-run `--check`.

### 4. Run it

```bash
/yt-extract https://www.youtube.com/watch?v=VIDEO_ID
```

If you skipped step 3, the first real run will offer to install any missing dependency when it's needed.

## Usage & Flags

```
/yt-extract <youtube-url> [<url2> [<url3>]] [flags]
```

| Flag | Effect |
|---|---|
| *(none)* | Metadata + description + structured summary + auto-save |
| `--comments` | Also fetch the top 10 comments |
| `--full-transcript` | Return the raw transcript instead of a summary |
| `--screenshots` | Extract screenshots at chapter markers (requires ffmpeg) |
| `--screenshots 0:30,2:15,5:00` | Extract screenshots at custom timestamps |
| `--no-save` | Skip auto-save; ask before writing to disk |
| `--check` | Verify dependencies only — no video extraction, no output file. Use this to trigger the install-on-demand flow for `yt-dlp` (and `ffmpeg` when combined with `--screenshots`) without doing a real run. |

### Examples

```bash
# Verify install only — no extraction, no output file
/yt-extract --check
/yt-extract --check --screenshots       # also verifies ffmpeg

# Single video — structured summary, auto-saved
/yt-extract https://www.youtube.com/watch?v=dQw4w9WgXcQ

# With comments and screenshots at chapter markers
/yt-extract https://youtu.be/abc123 --comments --screenshots

# Full raw transcript with custom screenshot timestamps
/yt-extract https://youtu.be/abc123 --full-transcript --screenshots 1:30,5:00,12:45

# Compare 3 videos on the same topic
/yt-extract https://youtu.be/a https://youtu.be/b https://youtu.be/c --comments
```

## How It Works

### Default flow (no screenshots)

```
  User
    │  /yt-extract <url1> [<url2> [<url3>]]
    ▼
┌──────────────────────────────────────────────┐
│  SKILL.md orchestrator                       │
│  parses flags, dispatches N subagents         │
└────────────────────┬─────────────────────────┘
                     │  parallel: one subagent per URL
       ┌─────────────┼─────────────┐
       ▼             ▼             ▼
   ┌──────┐      ┌──────┐      ┌──────┐
   │ SA 1 │      │ SA 2 │      │ SA 3 │       each runs:
   └──┬───┘      └──┬───┘      └──┬───┘       python yt-extract.py <url>
      │             │             │            ├─ yt-dlp → metadata / description
      │             │             │            ├─ yt-dlp → transcript (VTT)
      │             │             │            └─ yt-dlp → top comments (optional)
      ▼             ▼             ▼
┌──────────────────────────────────────────────┐
│  Structured Markdown (per URL)               │
│  ### Metadata      ### Description            │
│  ### Chapters      ### Transcript             │
│  ### Comments                                 │
└────────────────────┬─────────────────────────┘
                     │  each subagent summarizes its transcript
                     ▼
┌──────────────────────────────────────────────┐
│  Assemble output (+ Synthesis for 2-3 URLs)  │
│  Core Thesis · Main Points · Tools · Quotes  │
└────────────────────┬─────────────────────────┘
                     ▼
┌──────────────────────────────────────────────┐
│  Auto-save                                   │
│  yt-extract_2026-04-17_video-title-slug/     │
│    └─ yt-extract_2026-04-17_*.md             │
└──────────────────────────────────────────────┘
```

### Flow with `--screenshots`

Screenshots land in two places: **embedded inside the transcript** at their matching timestamps (so you can read and see in context), and **listed separately** in a `## Screenshots` section (for quick visual skimming).

```
  User
    │  /yt-extract <url> --screenshots
    ▼
┌──────────────────────────────────────────────┐
│  SKILL.md orchestrator                       │
│  dispatches subagent with --screenshots       │
└────────────────────┬─────────────────────────┘
                     ▼
┌──────────────────────────────────────────────┐
│  Subagent runs:                              │
│  python yt-extract.py <url> --screenshots    │
│    --output-base .                           │
│                                              │
│  Backend pipeline:                           │
│  1. yt-dlp  → metadata + VTT transcript      │
│  2. yt-dlp  → chapter markers (if present)   │
│  3. Create yt-extract_DATE_slug/             │
│     + screenshots/ subfolder                 │
│  4. ffmpeg  → capture frame at each marker   │
│               → <folder>/screenshots/*.png   │
│  5. VTT parser INTERLEAVES image refs        │
│     at matching transcript timestamps        │
│                                              │
│  stderr stream: [1/5] [2/5] … progress       │
└────────────────────┬─────────────────────────┘
                     ▼
┌──────────────────────────────────────────────┐
│  Markdown output (stdout)                    │
│                                              │
│  ### Transcript                              │
│  [00:00] Welcome to the video...             │
│  [00:30] Today we'll cover Docker            │
│          ![](screenshots/001_00m30s.png)     │
│  [02:15] First step: install Docker...       │
│          ![](screenshots/002_02m15s.png)     │
│                                              │
│  ### Screenshots                             │
│  - [00:30] Intro — 001_00m30s.png            │
│  - [02:15] Docker install — 002_02m15s.png   │
│                                              │
│  ### Screenshot Status                       │
│  2 screenshots requested, 2 extracted        │
│                                              │
│  OUTPUT_FOLDER: ./yt-extract_2026-04-20_slug │
└────────────────────┬─────────────────────────┘
                     ▼
┌──────────────────────────────────────────────┐
│  Skill reads OUTPUT_FOLDER, prepends         │
│  YAML frontmatter, writes the .md file       │
│  into the folder the script already created. │
│  No moves, no rewrites for single-video.     │
│                                              │
│  yt-extract_2026-04-20_slug/                 │
│    ├─ yt-extract_2026-04-20_*.md             │
│    └─ screenshots/                           │
│       ├─ 001_00m30s_intro.png                │
│       ├─ 002_02m15s_docker.png               │
│       └─ 003_05m00s_config.png               │
└──────────────────────────────────────────────┘
```

### Modes and where screenshots appear

| Mode | Where screenshots appear in the saved file |
|---|---|
| Summary + `--screenshots` at chapter markers (default) | Embedded inline **under each `## Chapters` entry** (1:1 mapping). The standalone `## Screenshots` section is suppressed. |
| Summary + `--screenshots 0:30,2:15,...` (custom timestamps) | Standalone `## Screenshots` section at the bottom (no chapter alignment possible). |
| `--full-transcript` + `--screenshots` at chapter markers | Transcript is pre-structured as `### [HH:MM] Chapter Title` h3 blocks — each heading is followed by the matching screenshot and the transcript text for that interval. `## Chapters` renders as a plain TOC. Standalone `## Screenshots` section is suppressed. |
| `--full-transcript` + `--screenshots` at custom timestamps | Each screenshot is embedded inline in the transcript with a preceding `### [HH:MM]` h3 heading (or `### [HH:MM] — Chapter Title` if the timestamp happens to fall inside a chapter). Standalone `## Screenshots` section is suppressed. |

The `## Screenshot Status` line (`"N screenshots requested, M successfully extracted"`) is always rendered when `--screenshots` was used, regardless of which mode.

### After a run completes

Every extraction ends with a concise **"What next?"** invitation that lists concrete follow-up queries you can fire at the extracted data — extract all tools as a checklist, translate the summary, drill into a specific chapter, write a blog draft, and so on — plus re-run hints for any flags you didn't use this time (`--comments`, `--full-transcript`, `--screenshots`). The transcript and summary stay in the current Claude Code session's context, so you can chain follow-ups without re-running anything.

### Components

- **`skills/yt-extract/SKILL.md`** — The skill definition. Parses URLs and flags, detects the host OS, checks dependencies, dispatches one subagent per URL for summarization, assembles the final Markdown output, handles auto-save and folder layout.
- **`scripts/yt-extract.py`** — The Python backend. Calls `yt-dlp` for metadata/subtitles/comments, parses VTT with timestamps, calls `ffmpeg` for screenshots, and owns deterministic markdown rendering details such as section ordering, timestamp formatting, screenshot filename conventions, and screenshot/transcript layout.

## Anatomy of a Saved File

Every saved analysis is a single Markdown file with YAML frontmatter. Here's the abstract skeleton for a **single-video** run with `--screenshots --comments`:

```markdown
---
title: "<video title>"
channel: "<channel name>"
date: "<upload date YYYY-MM-DD>"
url: "<youtube url>"
analyzed: "<today's date YYYY-MM-DD>"
flags: [screenshots, comments]
---

## <Video Title>
**Channel:** <…> | **Date:** <…> | **Duration:** <HH:MM:SS> | **Views:** <n> | **Likes:** <n>

---

## Description
<cleaned description — subscribe/social boilerplate stripped, tool links kept>

## Chapters
- [00:00] <chapter title>

  ![<chapter title>](screenshots/001_00m00s_<slug>.png)

- [02:15] <chapter title>

  ![<chapter title>](screenshots/002_02m15s_<slug>.png)

…

## Transcript Summary
> ℹ️ Auto-generated subtitles (<lang>)

#### Core Thesis
<1-2 sentences: central claim of the video>

#### Main Points
1. <insight>
2. <insight>
…

#### Tools & Resources Mentioned
- <tool or link>
- …

#### Key Quotes & Numbers
- <metric, statistic, verbatim quote>
- …

> 💡 Full transcript available — re-run with `--full-transcript` if needed.

## Screenshot Status
<N> screenshots requested, <M> successfully extracted

## Top Comments
1. <comment author> — <top comment text>
2. …
```

### Folder structure

**Single video:**

```
yt-extract_2026-04-16_video-title-slug/
├── yt-extract_2026-04-16_video-title-slug.md
└── screenshots/                     ← only with --screenshots
    ├── 001_00m30s_intro.png
    ├── 002_02m15s_installing-docker.png
    └── 003_05m00s_configuration.png
```

**Multi-video (2-3 URLs):**

```
yt-extract_2026-04-20_3-videos/
├── yt-extract_2026-04-20_3-videos.md            ← consolidated output
├── yt-extract_2026-04-20_video-one-slug/        ← per-video folder (from subagent 1)
│   └── screenshots/
│       └── 001_00m30s.png
├── yt-extract_2026-04-20_video-two-slug/        ← per-video folder (from subagent 2)
│   └── screenshots/
│       └── 001_01m00s.png
└── yt-extract_2026-04-20_video-three-slug/
    └── screenshots/
        └── 001_02m45s.png
```

Each per-video folder is a complete, standalone extraction unit — you can
move or rename any one of them independently. The consolidated `.md` at the
top references screenshots via the per-video folder path
(`yt-extract_2026-04-20_video-one-slug/screenshots/001_00m30s.png`).

### Multi-video frontmatter

```yaml
---
analyzed: "2026-04-16"
flags: [screenshots]
videos:
  - title: "Video 1 Title"
    channel: "Channel A"
    date: "2024-01-10"
    url: "https://youtu.be/aaa"
  - title: "Video 2 Title"
    channel: "Channel B"
    date: "2024-02-22"
    url: "https://youtu.be/bbb"
---
```

## Multi-Video Mode

When you pass 2 or 3 URLs, each video is extracted in parallel (one subagent per URL), and a final **Synthesis** section compares them:

- **Shared themes** — topics shared across videos
- **Differences & contradictions** — diverging approaches, conflicting statements
- **Overall key takeaways** — the most important insights across all videos
- **Tools & resources mentioned** — consolidated list of all tools, repos, links

Dependency checks still fire exactly once per run, not once per URL — so three parallel subagents with `--screenshots` produce a single ffmpeg prompt (or no prompt at all if ffmpeg is already installed).

## How yt-extract compares

There's no shortage of YouTube-summarization tools. Here's an honest, feature-by-feature comparison against five of the most popular alternatives. All data verified against the official product pages, official store listings, or neutral third-party reviews as of April 2026.

| Tool | Summary | Full transcript | Screenshots (video frames) | Multi-video batch + synthesis | Local Markdown export | Follow-up queries on extracted data |
|------|:-------:|:---------------:|:---:|:---:|:---:|:---:|
| **yt-extract** | ✅ structured (Thesis · Points · Tools · Quotes) | ✅ `--full-transcript` | ✅ chapters + custom timestamps | ✅ 2–3 URLs with cross-video synthesis | ✅ auto-saves `.md` with YAML frontmatter | ✅ Claude-native — ask follow-ups without copy-paste |
| [Summarize.tech](https://www.summarize.tech/) | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| [NoteGPT](https://notegpt.io/) | ✅ | ✅ | ❌ | ❌ | ⚠️¹ | ✅ |
| [Eightify](https://eightify.app/) | ✅ | ✅² | ❌ | ❌ | ❌ | ❌ |
| [Glasp YT Summary](https://glasp.co/youtube-summary) | ✅ | ✅² | ❌ | ❌ | ⚠️³ | ⚠️⁴ |
| [Merlin AI](https://www.getmerlin.in/) | ✅ | ✅ | ❌ | ❌ | ❌ | ⚠️⁵ |

**Footnotes:**

¹ NoteGPT has a `PDF → Markdown` converter, but no explicit `.md` download for transcripts or summaries.
² Eightify / Glasp: "Copy Transcript" puts the text on your clipboard — no file download.
³ Glasp: highlights can be exported as `.md` to Roam, Notion, or Obsidian — but full summary/transcript-to-`.md` export is not explicit.
⁴ Glasp uses your own ChatGPT / Claude / Gemini / Mistral account — follow-up questions happen inside that chat, not within the extension itself.
⁵ Merlin is a general-purpose AI chat assistant — so follow-up on extracted YouTube data is *possible* through its broader chat, but not documented as a dedicated feature.

### What this table honestly shows

- **Commodity features** (summary, transcript): nearly every tool has these. Anything else is table stakes.
- **Chapter-aligned screenshots** and **multi-video batch with synthesis**: the two columns where yt-extract appears to stand alone — no mainstream competitor markets these features.
- **Local Markdown export**: only yt-extract saves a full dated folder with YAML frontmatter by default. Others keep the result in a browser or clipboard.
- **Follow-up queries**: because yt-extract runs *inside* Claude Code, the extracted data is already in the assistant's context — you can immediately ask "summarize these 3 videos in one paragraph" or "extract all tools mentioned in point 4" without re-feeding anything.

### The honest trade-off

yt-extract requires [Claude Code](https://claude.com/claude-code) and two CLI dependencies (`yt-dlp`, optionally `ffmpeg`). Every tool in the table above works inside a browser with no setup. If you want a zero-install summary in 10 seconds and don't need transcripts, screenshots, batch mode, local files, or agent-native follow-ups — one of the browser tools will serve you faster. yt-extract is optimized for the case where you want the full extracted payload as a local artifact you can reuse, edit, search, and chain into further AI work.

## Prerequisites

Cross-platform: macOS, Linux, and Windows are all supported. Python 3.9+ is required (use `python3` on macOS/Linux, `python` on Windows — the skill picks the right one automatically).

**Required — [yt-dlp](https://github.com/yt-dlp/yt-dlp)** — YouTube data extraction:

```bash
# macOS
brew install yt-dlp

# Linux
pip install --user yt-dlp          # or: pipx install yt-dlp

# Windows
pip install yt-dlp                 # or: winget install yt-dlp
```

**Optional (for `--screenshots`) — [ffmpeg](https://ffmpeg.org/)** — frame extraction:

```bash
# macOS
brew install ffmpeg

# Linux
sudo apt install ffmpeg            # Debian/Ubuntu
sudo dnf install ffmpeg            # Fedora/RHEL

# Windows
winget install Gyan.FFmpeg
```

### Install-on-demand

If either dependency is missing when you run `/yt-extract`, the skill detects the host OS and offers to install it for you. When more than one install method is valid on your OS (e.g. `pip` vs `winget` on Windows for yt-dlp), you pick which one to run. On failure the skill shows a clear error with a link to the official documentation and the manual install commands.

- **yt-dlp** is always checked. Declining the install prompt aborts the run with a pointer to the [yt-dlp installation wiki](https://github.com/yt-dlp/yt-dlp/wiki/Installation).
- **ffmpeg** is only checked when you pass `--screenshots`. Declining the install proceeds without screenshots; the saved Markdown notes that screenshots were skipped. See the [ffmpeg download page](https://ffmpeg.org/download.html) for manual install.

## Troubleshooting

### `"Installation completed but <dep> is still not on PATH"` — Windows
This is the **expected first-time experience on Windows**. `winget` updates the user PATH, but your current shell keeps its stale PATH until you restart. Close Claude Code, reopen it, and re-run `/yt-extract --check` to verify everything is in place (no video extraction needed). One-time ritual per freshly installed dependency.

### `ffmpeg` install hangs or asks for a sudo password — Linux
The skill probes `sudo -n true` before attempting any sudo install. If you have no active sudo session, the skill aborts safely and prints the exact manual command instead of hanging. Open your terminal, run `sudo apt install -y ffmpeg` (or `dnf`), then re-run `/yt-extract`. To avoid sudo entirely for `yt-dlp`, use `pip install --user yt-dlp` or `pipx install yt-dlp`.

### `winget install` returns exit code 43
This means the package is already installed — not an error. As of v1.1.0, Step 0.6.C treats exit 43 the same as exit 0 and proceeds to verify PATH. If the binary is still missing from PATH, see the first troubleshooting entry (shell restart).

### No transcript shown
The video has no subtitles (neither manual nor auto-generated), or the language is not detected by yt-dlp. The analysis continues with metadata, description, and comments; the summary section shows `❌ No transcript available.`

### No chapter markers — `--screenshots` asks where to take frames
The video has no chapter markers. The skill prompts you: either auto-distribute evenly (1 screenshot per 2 minutes, max 10), or enter custom timestamps. You can also pass timestamps up front with `--screenshots 0:30,2:15,5:00`.

### Private / age-restricted / members-only videos
Not supported. `yt-dlp` requires authentication for these, which yt-extract does not configure. Use `yt-dlp` manually with cookies if you need this.

### Playlists
Not supported. Pass individual video URLs only. Multi-video mode accepts up to 3 URLs in one call.

### Screenshot image links appear broken after moving the folder
The saved MD uses **relative** image paths (`screenshots/001_….png`). As long as the folder stays intact, links work. Moving only the `.md` out of its folder breaks the links — keep the whole folder together.

## FAQ

**Q: Does this work for YouTube Shorts?**
A: Yes, Shorts are treated as normal videos. No special handling needed.

**Q: Can I process livestreams?**
A: Only after they end — the transcript becomes available when the stream is archived. An ongoing live stream shows a `"Ongoing livestream — transcript available only after it ends"` note; metadata is still extracted.

**Q: Can I feed cookies to yt-dlp for age-gated content?**
A: Not currently. The skill doesn't expose `yt-dlp --cookies` yet. File an issue if you need it.

**Q: Why are screenshots stripped from the summary but kept in the raw transcript?**
A: The summary aims to be a clean, scannable briefing. Image refs clutter that. The raw transcript preserves them in context, and the separate `## Screenshots` section gives you a visual index either way.

**Q: How does it pick which screenshots to take?**
A: If the video has chapter markers → one per marker. If not → the skill asks you whether to auto-distribute evenly or specify timestamps. You can also pass `--screenshots 0:30,2:15,5:00` to skip the prompt.

**Q: Can the output be piped into another tool?**
A: Yes. The saved Markdown has a YAML frontmatter block and predictable section headings (`## Description`, `## Transcript Summary`, `## Top Comments`, etc.) — easy to parse or feed back into Claude for follow-up analysis.

## Limitations & Legal Notes

- **YouTube Terms of Service.** Downloading video data via `yt-dlp` may conflict with YouTube's ToS depending on your jurisdiction and use case. This plugin does **not** download video files — it only pulls metadata, subtitles, and comment text. Use responsibly and verify ToS compliance for your workflow.
- **Copyright & Fair Use.** Extracted transcripts, comments, and screenshots are copyrighted by their creators. Quoting, summarizing, and personal reference use are generally considered fair use in many jurisdictions; redistribution or commercial reuse typically is not. You are responsible for how you use the output.
- **Rate limits.** `yt-dlp` may hit YouTube rate limits on heavy batch use. This plugin processes at most 3 URLs per invocation, which is far below typical limits — but repeated back-to-back calls may still trip a temporary soft-block. If that happens, wait a few minutes and retry.

## Contributing

Issues, feature requests, and PRs are welcome on [GitHub](https://github.com/muckybuzzwoo/claude-code-youtube-extract).

Before opening a PR, please:
- Open an issue first for non-trivial changes so the design can be discussed before implementation
- Follow the architectural conventions in [CLAUDE.md](CLAUDE.md) (single skill + single script; English everywhere; `${CLAUDE_PLUGIN_ROOT}/scripts/yt-extract.py` invocation pattern)
- Update [CHANGELOG.md](CHANGELOG.md) under the `[Unreleased]` heading

Good first issues: additional install methods (e.g. `choco` on Windows, `snap` on Linux), cookie-auth support for private videos, playlist-URL expansion.

## License

[Apache-2.0](LICENSE) © Mucky / [buzzwoo](https://www.buzzwoo.de)

---

Version: 1.3.0 — [Changelog](CHANGELOG.md)
