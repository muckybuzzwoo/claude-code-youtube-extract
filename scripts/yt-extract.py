#!/usr/bin/env python3
"""
yt-extract.py — Single-call YouTube video data extractor for yt-extract.
Handles metadata, transcript, optional comments, and optional screenshots.
Returns structured markdown to stdout.

Usage:
    python yt-extract.py <URL> [--comments] [--screenshots [TIMESTAMPS]]
"""

from __future__ import annotations

import sys
import os
import re
import json
import glob
import subprocess
import tempfile
import argparse
import shutil
import datetime

# Force UTF-8 on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    os.environ["PYTHONUTF8"] = "1"

TMPDIR = tempfile.gettempdir()


def run_ytdlp(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["yt-dlp"] + args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


# --- Utility functions ---


def slugify(text: str, max_length: int = 50) -> str:
    """Convert text to URL-safe slug."""
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text).strip("-")
    text = re.sub(r"-+", "-", text)
    return text[:max_length].rstrip("-")


def emit_stage(current: int, total: int, text: str) -> None:
    """Emit a progress stage marker on stderr, flushed immediately."""
    print(f"[{current}/{total}] {text}", file=sys.stderr, flush=True)


def strip_overlap(prev_text: str, next_text: str) -> str:
    """Return next_text with the longest word-prefix also present as word-suffix
    of prev_text stripped off. Used to collapse YouTube rolling-caption
    overlaps (each cue repeats the tail of the previous cue).

    Word-level comparison: 'Hello world' overlapping with 'world today' yields
    'today'. Idempotent for non-overlapping inputs (no strip, next_text returned
    verbatim).
    """
    prev_words = prev_text.split()
    next_words = next_text.split()
    max_k = min(len(prev_words), len(next_words))
    for k in range(max_k, 0, -1):
        if prev_words[-k:] == next_words[:k]:
            return " ".join(next_words[k:])
    return next_text


def format_timestamp_display(seconds: float) -> str:
    """Format seconds as M:SS or H:MM:SS for display."""
    s = int(seconds)
    h, remainder = divmod(s, 3600)
    m, sec = divmod(remainder, 60)
    if h > 0:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


def format_timestamp_filename(seconds: float) -> str:
    """Format seconds as MMmSSs or HhMMmSSs for filenames."""
    s = int(seconds)
    h, remainder = divmod(s, 3600)
    m, sec = divmod(remainder, 60)
    if h > 0:
        return f"{h}h{m:02d}m{sec:02d}s"
    return f"{m:02d}m{sec:02d}s"


def parse_timestamp(ts_str: str) -> float:
    """Parse user timestamp to seconds. Accepts: SS, M:SS, MM:SS, H:MM:SS, HH:MM:SS."""
    ts_str = ts_str.strip()
    if re.match(r"^\d+(\.\d+)?$", ts_str):
        return float(ts_str)
    parts = ts_str.split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    raise ValueError(f"Invalid timestamp: {ts_str}")


def parse_vtt_timestamp(ts_str: str) -> float:
    """Parse VTT timestamp to seconds. Accepts HH:MM:SS.mmm and H:MM:SS.mmm."""
    match = re.match(r"(\d+):(\d{2}):(\d{2})\.(\d{3})", ts_str.strip())
    if match:
        h, m, s, ms = match.groups()
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
    # Fallback: try without milliseconds
    match2 = re.match(r"(\d+):(\d{2}):(\d{2})", ts_str.strip())
    if match2:
        h, m, s = match2.groups()
        return int(h) * 3600 + int(m) * 60 + int(s)
    print(f"WARNING: Could not parse VTT timestamp: {ts_str}", file=sys.stderr)
    return 0.0


def format_date(upload_date: str) -> str:
    if len(upload_date) == 8:
        return f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}"
    return upload_date


def render_metadata(meta: dict) -> str:
    return "\n".join([
        "### Metadata",
        f"title: {meta['title']}",
        f"channel: {meta['channel']}",
        f"date: {format_date(meta['upload_date'])}",
        f"duration: {meta['duration_string']}",
        f"duration_seconds: {meta['duration']}",
        f"views: {meta['view_count']}",
        f"likes: {meta['like_count']}",
        f"is_live: {meta['is_live']}",
        f"was_live: {meta['was_live']}",
        "",
    ])


def render_description(description: str) -> str:
    return "\n".join([
        "### Description",
        filter_description(description),
        "",
    ])


def render_chapters(chapters: list[dict]) -> str:
    if not chapters:
        return ""

    lines = ["### Chapters"]
    for ch in chapters:
        ts_display = format_timestamp_display(ch["start_time"])
        lines.append(f"- [{ts_display}] {ch['title']}")
    lines.append("")
    return "\n".join(lines)


def render_transcript_info(sub_hint: str, duration: float) -> str:
    lines = ["### Transcript Info", sub_hint]
    if duration and duration > 3600:
        lines.append(f"Video is {int(duration) // 60} min long — full transcript")
    lines.append("")
    return "\n".join(lines)


def render_transcript(
    transcript: str,
    segments: list[tuple[float, str]],
    screenshots: list[tuple[float, str]],
    chapters: list[dict],
) -> str:
    lines = ["### Transcript"]
    if transcript:
        if screenshots and segments:
            lines.append(embed_screenshots_in_transcript(segments, screenshots, chapters))
        else:
            lines.append(transcript)
    else:
        lines.append("No transcript available.")
    lines.append("")
    return "\n".join(lines)


def render_screenshots_section(
    screenshots_enabled: bool,
    screenshot_marker: str,
    screenshots: list[tuple[float, str]],
    chapters: list[dict],
    duration: float,
) -> str:
    if not screenshots_enabled:
        return ""

    lines = ["### Screenshots"]
    if screenshot_marker == "FFMPEG_MISSING":
        lines.append("FFMPEG_MISSING")
    elif screenshot_marker == "SCREENSHOTS_ASK_USER":
        lines.append("SCREENSHOTS_ASK_USER")
        lines.append(f"video_duration: {duration}")
    else:
        for ts, filename in screenshots:
            chapter_title = get_chapter_for_timestamp(ts, chapters)
            ts_display = format_timestamp_display(ts)
            rel_path = f"screenshots/{filename}"
            if chapter_title:
                lines.append(f"- ![{ts_display} — {chapter_title}]({rel_path}) {ts_display} — {chapter_title}")
            else:
                lines.append(f"- ![{ts_display}]({rel_path}) {ts_display}")
    lines.append("")
    return "\n".join(lines)


def render_screenshot_status(
    screenshots_enabled: bool,
    screenshot_marker: str,
    screenshot_requested: int,
    screenshots: list[tuple[float, str]],
    screenshot_warnings: list[str],
) -> str:
    if not screenshots_enabled:
        return ""

    lines = ["### Screenshot Status"]
    if screenshot_marker:
        lines.append(screenshot_marker)
    elif screenshot_requested > 0:
        success = len(screenshots)
        lines.append(
            f"{screenshot_requested} screenshots requested, {success} successfully extracted."
        )
    for warning in screenshot_warnings:
        lines.append(f"- WARNING: {warning}")
    lines.append("")
    return "\n".join(lines)


def render_comments(comments_requested: bool, comments: list[dict]) -> str:
    lines = ["### Comments"]
    if not comments_requested:
        lines.append("SKIPPED")
    elif comments:
        for i, c in enumerate(comments, 1):
            lines.append(f"{i}. **{c['author']}** (👍 {c['likes']}) — {c['text']}")
    else:
        lines.append("Comments not available.")
    return "\n".join(lines)


# --- Core extraction functions ---


def extract_metadata(url: str) -> dict | None:
    result = run_ytdlp(["--dump-json", "--no-playlist", "--no-warnings", url])
    if result.returncode != 0:
        return None
    try:
        d = json.loads(result.stdout)
        return {
            "id": d.get("id", ""),
            "title": d.get("title", ""),
            "channel": d.get("channel", ""),
            "upload_date": d.get("upload_date", ""),
            "duration_string": d.get("duration_string", ""),
            "duration": d.get("duration", 0),
            "view_count": d.get("view_count", 0),
            "like_count": d.get("like_count", 0),
            "description": d.get("description", ""),
            "is_live": d.get("is_live", False),
            "was_live": d.get("was_live", False),
            "chapters": d.get("chapters") or [],
        }
    except (json.JSONDecodeError, KeyError):
        return None


def download_and_process_vtt(url: str, video_id: str) -> tuple[str, str, list[tuple[float, str]]]:
    """Returns (transcript_text, subtitle_hint, segments).
    segments is a list of (start_seconds, text) tuples for timestamp mapping.
    """
    prefix = os.path.join(TMPDIR, f"yt_analyze_{video_id}")

    # Clean up any previous files for this ID
    for f in glob.glob(f"{prefix}*"):
        os.remove(f)

    result = run_ytdlp([
        "--write-auto-subs", "--write-subs",
        "--sub-langs", ".*orig,en",
        "--sub-format", "vtt", "--convert-subs", "vtt",
        "--skip-download", "--no-playlist", "--no-warnings",
        "-o", f"{prefix}.%(ext)s",
        url,
    ])

    # Find VTT files
    vtt_files = glob.glob(f"{prefix}*.vtt")
    if not vtt_files:
        return "", "none", []

    vtt_path = vtt_files[0]
    filename = os.path.basename(vtt_path)

    # Auto-detection: check filename pattern only (yt-dlp marks auto-subs
    # in filenames; stderr contains "auto" in unrelated messages too)
    is_auto = ".auto." in filename.lower()

    # Extract language from filename pattern: yt_analyze_ID.LANG.vtt
    lang_match = re.search(r"\.([a-z]{2}(?:-[a-z]+)?(?:-orig)?)\.vtt$", filename, re.I)
    lang = lang_match.group(1) if lang_match else "en"

    # Process VTT to plain text AND timestamped segments
    with open(vtt_path, encoding="utf-8", errors="replace") as f:
        content = f.read()

    segments = []
    current_start = 0.0
    current_lines = []
    in_metadata_block = False  # NOTE/STYLE blocks span until next blank line

    for line in content.split("\n"):
        line = line.strip()

        # Blank line: end any open NOTE/STYLE block
        if not line:
            in_metadata_block = False
            continue
        # WebVTT header + file-level metadata fields
        if line.startswith("WEBVTT"):
            continue
        if re.match(r"^(Kind|Language):\s", line):
            continue
        # NOTE / STYLE blocks span lines until the next blank line
        if line.startswith("NOTE") or line.startswith("STYLE"):
            in_metadata_block = True
            continue
        if in_metadata_block:
            continue
        # Cue identifier lines (pure digits)
        if re.match(r"^\d+$", line):
            continue

        # Parse VTT timestamp lines: 00:02:15.000 --> 00:02:18.500
        arrow_match = re.match(
            r"(\d{2}:\d{2}:\d{2}\.\d{3})\s*-->\s*\d{2}:\d{2}:\d{2}\.\d{3}",
            line,
        )
        if arrow_match:
            # Save previous segment
            if current_lines:
                segments.append((current_start, " ".join(current_lines)))
            current_start = parse_vtt_timestamp(arrow_match.group(1))
            current_lines = []
            continue

        # Skip bare timestamp lines (without -->)
        if re.match(r"^\d{2}:\d{2}:\d{2}", line):
            continue

        # Text line — strip VTT tags
        clean = re.sub(r"<[^>]+>", "", line).strip()
        if clean:
            current_lines.append(clean)

    # Don't forget the last segment
    if current_lines:
        segments.append((current_start, " ".join(current_lines)))

    # Cue-based rolling-overlap dedup.
    # YouTube auto-captions emit a 3-line rolling window where each cue repeats
    # the tail of the previous cue. The fix: for each new cue, strip the longest
    # word-prefix that matches the suffix of the already-accumulated text. One
    # pass catches both [A,B,C] -> [B,C,D] overlaps and fully-redundant cues.
    deduped_segments: list[tuple[float, str]] = []
    for start, text in segments:
        if not deduped_segments:
            deduped_segments.append((start, text))
            continue
        _, prev_text = deduped_segments[-1]
        stripped = strip_overlap(prev_text, text).strip()
        if stripped:
            deduped_segments.append((start, stripped))
        # else: this cue was entirely contained in the previous one — drop it.

    transcript = " ".join(text for _, text in deduped_segments).strip()

    # Cleanup temp files
    for f in glob.glob(f"{prefix}*"):
        os.remove(f)

    hint = f"auto-generated ({lang})" if is_auto else f"manual ({lang})"
    return transcript, hint, deduped_segments


def fetch_comments(url: str) -> list[dict]:
    result = run_ytdlp([
        "--write-comments",
        "--extractor-args", "youtube:comment_sort=top;max_comments=20,20,20,20",
        "--skip-download", "--dump-json",
        "--no-playlist", "--no-warnings",
        url,
    ])

    if result.returncode != 0:
        return []

    try:
        d = json.loads(result.stdout)
        comments = d.get("comments", [])
        comments.sort(key=lambda x: x.get("like_count", 0), reverse=True)
        return [
            {
                "author": c.get("author", ""),
                "likes": c.get("like_count", 0),
                "text": c.get("text", "")[:300],
            }
            for c in comments[:10]
        ]
    except (json.JSONDecodeError, KeyError):
        return []


def filter_description(desc: str) -> str:
    """Keep: tool links, GitHub repos, docs, chapter markers. Remove: social/subscribe/sponsor boilerplate."""
    lines = desc.split("\n")
    filtered = []
    skip_patterns = [
        r"(?i)(subscribe|follow\s+(me|us)|patreon|donation|sponsor|merch|social)",
        r"(?i)(instagram|twitter|x\.com|tiktok|facebook|discord\.gg|linkedin\.com/in/)",
    ]

    for line in lines:
        if any(re.search(p, line) for p in skip_patterns):
            continue
        filtered.append(line)

    return "\n".join(filtered).strip()


# --- Screenshot functions ---


def check_ffmpeg() -> bool:
    """Check if ffmpeg is available in PATH."""
    return shutil.which("ffmpeg") is not None


def get_chapter_for_timestamp(timestamp: float, chapters: list[dict]) -> str | None:
    """Find chapter title for a given timestamp."""
    for ch in chapters:
        if ch.get("start_time", 0) <= timestamp < ch.get("end_time", float("inf")):
            return ch.get("title", "")
    return None


def resolve_timestamps(
    screenshots_arg: str, chapters: list[dict], duration: float,
    warnings: list[str],
) -> list[float] | str:
    """Determine which timestamps to screenshot.
    Returns list of seconds, or 'ASK_USER' if auto mode but no chapters.
    Appends any issues to warnings list.
    """
    if screenshots_arg == "auto":
        if chapters:
            # Validate chapter timestamps against duration
            return [
                ch["start_time"] for ch in chapters
                if 0 <= ch.get("start_time", -1) <= duration
            ]
        return "ASK_USER"

    # Parse comma-separated timestamps
    timestamps = []
    for ts in screenshots_arg.split(","):
        ts = ts.strip()
        if not ts:
            continue
        try:
            secs = parse_timestamp(ts)
            if 0 <= secs <= duration:
                timestamps.append(secs)
            else:
                msg = f"Timestamp {ts} ({secs}s) outside video duration ({duration}s), skipping."
                warnings.append(msg)
                print(f"WARNING: {msg}", file=sys.stderr)
        except ValueError as e:
            msg = f"{e}, skipping."
            warnings.append(msg)
            print(f"WARNING: {msg}", file=sys.stderr)

    return sorted(timestamps)


def get_stream_url(url: str) -> str | None:
    """Get direct video stream URL via yt-dlp -g."""
    result = run_ytdlp([
        "-g", "-f", "best[height<=1080]/best",
        "--no-playlist", "--no-warnings", url,
    ])
    if result.returncode != 0:
        return None
    lines = result.stdout.strip().split("\n")
    return lines[0] if lines else None


def extract_screenshots(
    url: str,
    timestamps: list[float],
    out_dir: str,
    chapters: list[dict],
    warnings: list[str],
) -> list[tuple[float, str]]:
    """Extract PNG screenshots at given timestamps via ffmpeg.
    Writes files directly into out_dir (caller owns that path).
    Returns [(timestamp_seconds, filename), ...] — filename is the basename
    only, so callers can build whatever relative path they need for markdown.
    Appends any issues to warnings list.
    """
    stream_url = get_stream_url(url)
    if not stream_url:
        msg = "Could not fetch stream URL. No screenshots extracted."
        warnings.append(msg)
        print(f"ERROR: {msg}", file=sys.stderr)
        return []

    os.makedirs(out_dir, exist_ok=True)

    results = []
    for i, ts in enumerate(timestamps, 1):
        chapter_title = get_chapter_for_timestamp(ts, chapters)
        ts_file = format_timestamp_filename(ts)

        if chapter_title:
            chapter_slug = slugify(chapter_title, 40)
            filename = f"{i:03d}_{ts_file}_{chapter_slug}.png"
        else:
            filename = f"{i:03d}_{ts_file}.png"

        filepath = os.path.join(out_dir, filename)

        # -y -loglevel BEFORE -ss; -ss BEFORE -i for fast input seeking
        cmd = [
            "ffmpeg",
            "-y", "-loglevel", "error",
            "-ss", str(int(ts)),
            "-i", stream_url,
            "-frames:v", "1",
            filepath,
        ]

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if proc.returncode == 0 and os.path.exists(filepath):
                results.append((ts, filename))
            else:
                err = proc.stderr.strip() if proc.stderr else "unknown error"
                msg = f"Frame at {format_timestamp_display(ts)} failed: {err}"
                warnings.append(msg)
                print(f"WARNING: {msg}", file=sys.stderr)
        except subprocess.TimeoutExpired:
            msg = f"Frame at {format_timestamp_display(ts)} timed out (>60s)"
            warnings.append(msg)
            print(f"WARNING: {msg}", file=sys.stderr)

    return results


def _is_chapter_aligned(
    screenshots: list[tuple[float, str]],
    chapters: list[dict],
) -> bool:
    """True when there is exactly one screenshot per chapter and their
    timestamps line up within 1s. Used to pick the rendering strategy.
    """
    if not screenshots or not chapters or len(screenshots) != len(chapters):
        return False
    return all(
        abs(ss_ts - ch.get("start_time", -1)) < 1.0
        for (ss_ts, _), ch in zip(screenshots, chapters)
    )


def _chapter_end_time(chapters: list[dict], idx: int) -> float:
    """Return the end time for chapter idx — fall back to the next chapter's
    start, then to +∞ for the last chapter. yt-dlp usually supplies end_time,
    but this stays defensive in case it is missing.
    """
    ch = chapters[idx]
    end = ch.get("end_time")
    if end is not None:
        return float(end)
    if idx + 1 < len(chapters):
        return float(chapters[idx + 1].get("start_time", float("inf")))
    return float("inf")


def _render_chapter_structured(
    segments: list[tuple[float, str]],
    screenshots: list[tuple[float, str]],
    chapters: list[dict],
) -> str:
    """Transcript layout for chapter-aligned runs: one h3 block per chapter,
    screenshot right after the heading, then all transcript segments whose
    timestamp falls inside the chapter's interval.
    """
    parts: list[str] = []
    for i, chapter in enumerate(chapters):
        ch_start = float(chapter.get("start_time", 0.0))
        ch_end = _chapter_end_time(chapters, i)
        ch_title = chapter.get("title", "").strip()
        _, ss_filename = screenshots[i]
        ts_display = format_timestamp_display(ch_start)

        heading = f"### [{ts_display}] {ch_title}" if ch_title else f"### [{ts_display}]"
        alt = f"{ts_display} — {ch_title}" if ch_title else ts_display

        parts.append(f"\n\n{heading}\n\n")
        parts.append(f"![{alt}](screenshots/{ss_filename})\n\n")

        for seg_ts, seg_text in segments:
            if ch_start <= seg_ts < ch_end:
                parts.append(seg_text + " ")

    return "".join(parts).strip()


def _render_inline_with_heading(
    segments: list[tuple[float, str]],
    screenshots: list[tuple[float, str]],
    chapters: list[dict],
) -> str:
    """Fallback layout when the run is not chapter-aligned (custom timestamps,
    no chapters, or count mismatch). Each screenshot gets an h3 heading just
    before the image so readers see the timestamp context in full-transcript
    mode. If the timestamp happens to fall inside a chapter, the chapter title
    is appended to the heading after an em-dash.
    """
    if not segments:
        return ""

    screenshot_map: dict[int, list[str]] = {}
    for ts, filename in screenshots:
        best_idx = 0
        for idx, (seg_ts, _) in enumerate(segments):
            if seg_ts <= ts:
                best_idx = idx
            else:
                break

        chapter_title = get_chapter_for_timestamp(ts, chapters)
        ts_display = format_timestamp_display(ts)

        if chapter_title:
            heading = f"### [{ts_display}] — {chapter_title}"
            alt = f"{ts_display} — {chapter_title}"
        else:
            heading = f"### [{ts_display}]"
            alt = ts_display

        ref = f"\n\n{heading}\n\n![{alt}](screenshots/{filename})\n\n"
        screenshot_map.setdefault(best_idx, []).append(ref)

    parts: list[str] = []
    for idx, (_, text) in enumerate(segments):
        if idx in screenshot_map:
            for ref in screenshot_map[idx]:
                parts.append(ref)
        parts.append(text + " ")

    return "".join(parts).strip()


def embed_screenshots_in_transcript(
    segments: list[tuple[float, str]],
    screenshots: list[tuple[float, str]],
    chapters: list[dict],
) -> str:
    """Insert screenshots into the transcript. Picks between two layouts:

    - Chapter-structured (one screenshot per chapter, timestamps aligned):
      ``### [HH:MM] Chapter Title`` heading, image, segments of that chapter.
    - Inline-with-heading fallback (custom timestamps or mismatch): the
      existing inline insert, but each image is preceded by its own
      ``### [HH:MM]`` heading for scannability.

    screenshots is [(ts, filename), ...] — filenames resolved against the
    sibling ``screenshots/`` folder where the markdown will live.
    """
    if not segments:
        return ""

    if _is_chapter_aligned(screenshots, chapters):
        return _render_chapter_structured(segments, screenshots, chapters)
    return _render_inline_with_heading(segments, screenshots, chapters)


# --- Main ---


def main():
    parser = argparse.ArgumentParser(description="Extract YouTube video data")
    parser.add_argument("url", help="YouTube URL")
    parser.add_argument("--comments", action="store_true", help="Also fetch top comments")
    parser.add_argument(
        "--screenshots", nargs="?", const="auto", default=None,
        help="Extract screenshots. Without value: use chapter markers. "
             "With comma-separated timestamps: 0:30,2:15,5:00",
    )
    parser.add_argument(
        "--output-base", default=".",
        help="Base directory for the output folder (default: current directory). "
             "Script creates '<base>/yt-extract_<date>_<slug>/' inside it.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite existing target folder. Without this flag the script "
             "exits with code 2 + 'FOLDER_EXISTS: <path>' on stderr when the "
             "target already exists.",
    )
    args = parser.parse_args()

    url = args.url

    # --- Stage count (adaptive to enabled features) ---
    stages = ["metadata", "transcript"]
    if args.comments:
        stages.append("comments")
    if args.screenshots is not None:
        stages.append("screenshots")
    stages.append("output")
    total_stages = len(stages)
    stage_idx = 0

    # --- Step 1: Metadata ---
    stage_idx += 1
    emit_stage(stage_idx, total_stages, "Fetching metadata")
    meta = extract_metadata(url)
    if not meta:
        print(f"ERROR: Could not fetch metadata for {url}")
        sys.exit(1)

    # --- Compute target folder ---
    date_str = datetime.date.today().isoformat()
    slug = slugify(meta["title"])
    target = os.path.join(args.output_base, f"yt-extract_{date_str}_{slug}")

    # --- Collision guard ---
    if os.path.isdir(target) and not args.force:
        print(f"FOLDER_EXISTS: {target}", file=sys.stderr, flush=True)
        sys.exit(2)

    os.makedirs(target, exist_ok=True)

    # --- Step 2: Transcript ---
    stage_idx += 1
    emit_stage(stage_idx, total_stages, "Downloading transcript")
    transcript, sub_hint, segments = download_and_process_vtt(url, meta["id"])

    # --- Step 3: Comments (optional) ---
    comments = []
    if args.comments:
        stage_idx += 1
        emit_stage(stage_idx, total_stages, "Fetching comments")
        comments = fetch_comments(url)

    # --- Step 4: Screenshots (optional) ---
    screenshots = []
    screenshot_warnings: list[str] = []
    screenshot_requested = 0
    screenshot_marker = ""  # "FFMPEG_MISSING" or "SCREENSHOTS_ASK_USER"
    if args.screenshots is not None:
        stage_idx += 1
        if not check_ffmpeg():
            screenshot_marker = "FFMPEG_MISSING"
            screenshot_warnings.append("ffmpeg not found — no screenshots extracted.")
            emit_stage(stage_idx, total_stages, "Screenshots skipped (ffmpeg missing)")
        else:
            timestamps = resolve_timestamps(
                args.screenshots, meta["chapters"], meta["duration"],
                screenshot_warnings,
            )
            if timestamps == "ASK_USER":
                screenshot_marker = "SCREENSHOTS_ASK_USER"
                emit_stage(stage_idx, total_stages, "Screenshots deferred (no chapters)")
            elif timestamps:
                screenshot_requested = len(timestamps)
                emit_stage(
                    stage_idx, total_stages,
                    f"Extracting {screenshot_requested} screenshots",
                )
                out_dir = os.path.join(target, "screenshots")
                screenshots = extract_screenshots(
                    url, timestamps, out_dir, meta["chapters"],
                    screenshot_warnings,
                )
            else:
                emit_stage(stage_idx, total_stages, "No valid screenshot timestamps")

    # --- Step 5: Output ---
    stage_idx += 1
    emit_stage(stage_idx, total_stages, "Writing output")

    # --- Output structured markdown ---

    sections = [
        render_metadata(meta),
        render_description(meta["description"]),
        render_chapters(meta["chapters"]),
        render_transcript_info(sub_hint, meta["duration"]),
        render_transcript(transcript, segments, screenshots, meta["chapters"]),
        render_screenshots_section(
            args.screenshots is not None,
            screenshot_marker,
            screenshots,
            meta["chapters"],
            meta["duration"],
        ),
        render_screenshot_status(
            args.screenshots is not None,
            screenshot_marker,
            screenshot_requested,
            screenshots,
            screenshot_warnings,
        ),
        render_comments(args.comments, comments),
    ]
    print("\n".join(section for section in sections if section))

    # --- Trailer: tell the orchestrator where the output folder lives ---
    # Forward slashes so the marker is stable across platforms — the skill
    # parses this line verbatim to decide where to write the MD file.
    print()
    print(f"OUTPUT_FOLDER: {target.replace(os.sep, '/')}")


if __name__ == "__main__":
    main()
