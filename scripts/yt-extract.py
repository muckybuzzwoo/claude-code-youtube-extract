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
from collections.abc import Sequence

# Force UTF-8 on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    os.environ["PYTHONUTF8"] = "1"

TMPDIR = tempfile.gettempdir()

# Scene-detection defaults (select filter scene score, range 0..1)
DEFAULT_SCENE_THRESHOLD = 0.04
SCENE_MIN_GAP_SECONDS = 4.0
SCENE_MAX_SCREENSHOTS = 50
SCENE_SEEK_OFFSET = 0.5  # settle offset past the detected change (fades)

# Perceptual frame-dedup (scenes mode): compare 16x16 grayscale thumbnails.
# Mean-absolute-difference (0..255 scale) at or below the threshold counts as a
# near-duplicate and is dropped. 16x16 gray keeps it cheap and layout-robust.
PERCEPTUAL_DEDUP_THRESHOLD = 2.0
THUMBNAIL_SIZE = 16


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


def extract_video_id(url: str) -> str | None:
    """Extract the 11-char YouTube video ID from common URL forms
    (``watch?v=``, ``youtu.be/``, ``/shorts/``, ``/embed/``, ``/live/``).
    Returns None on no match. Used by --transcript-only mode to name the
    output folder without paying for a metadata fetch.
    """
    m = re.search(r"(?:v=|/shorts/|/embed/|/live/|youtu\.be/)([A-Za-z0-9_-]{11})", url)
    return m.group(1) if m else None


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
    deduped: int = 0,
) -> str:
    if not screenshots_enabled:
        return ""

    lines = ["### Screenshot Status"]
    if screenshot_marker:
        lines.append(screenshot_marker)
    elif screenshot_requested > 0:
        kept = len(screenshots)
        # "extracted" counts frames ffmpeg actually wrote (kept + deduped), so
        # perceptual dedup never looks like an extraction failure.
        extracted = kept + deduped
        line = f"{screenshot_requested} screenshots requested, {extracted} successfully extracted"
        if deduped:
            line += f", {deduped} near-duplicate(s) removed ({kept} kept)"
        lines.append(line + ".")
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


def parse_screenshots_mode(arg: str) -> tuple[str, float | None]:
    """Classify the --screenshots argument value.

    Returns (mode, threshold):
    - 'scenes'              -> ('scenes', DEFAULT_SCENE_THRESHOLD)
    - 'scenes=0.05'         -> ('scenes', 0.05) — raises ValueError outside (0, 1]
    - 'chapters' / 'auto'   -> ('chapters', None) — 'auto' was the pre-1.8.0
      const value; keeping the alias preserves old behavior for any direct
      caller still passing it.
    - anything else         -> ('timestamps', None), raw arg flows into the
      existing comma-separated parser.
    """
    if arg in ("chapters", "auto"):
        return ("chapters", None)
    if arg == "scenes":
        return ("scenes", DEFAULT_SCENE_THRESHOLD)
    if arg.startswith("scenes="):
        threshold = float(arg.split("=", 1)[1])  # ValueError on non-float
        if not 0 < threshold <= 1:
            raise ValueError(f"Scene threshold must be in (0, 1], got {threshold}")
        return ("scenes", threshold)
    return ("timestamps", None)


def parse_scene_timestamps(ffmpeg_output: str) -> list[float]:
    """Extract pts_time values from ffmpeg ``metadata=print:file=-`` output.

    Expected line shape (verified against ffmpeg output):
        frame:0    pts:1024    pts_time:0.0666667
        lavfi.scene_score=0.090931
    pts_time may lack a decimal part (``pts_time:1``). Everything that does
    not match is ignored, so format drift degrades to fewer matches, not a
    crash.
    """
    return sorted(
        float(m.group(1))
        for m in re.finditer(r"pts_time:(\d+(?:\.\d+)?)", ffmpeg_output)
    )


def apply_min_gap(timestamps: list[float], min_gap: float = SCENE_MIN_GAP_SECONDS) -> list[float]:
    """Drop timestamps closer than min_gap to the last kept one (keeps the
    first of each cluster). Input is sorted defensively."""
    kept: list[float] = []
    for ts in sorted(timestamps):
        if not kept or ts - kept[-1] >= min_gap:
            kept.append(ts)
    return kept


def thin_evenly(timestamps: list[float], max_count: int = SCENE_MAX_SCREENSHOTS) -> list[float]:
    """Reduce to max_count entries by even index sampling, preserving the
    first and last timestamp. Returns the list unchanged when small enough."""
    n = len(timestamps)
    if n <= max_count:
        return timestamps
    indices = {round(i * (n - 1) / (max_count - 1)) for i in range(max_count)}
    return [timestamps[i] for i in sorted(indices)]


def frame_delta(a: Sequence[int], b: Sequence[int]) -> float:
    """Mean absolute difference between two equal-length pixel sequences
    (16x16 grayscale thumbnails, values 0..255).

    Returns 0.0 for two empty inputs and ``inf`` on a length mismatch, so a
    thumbnail that could not be built the same way as its neighbour is treated
    as "definitely different" and kept rather than silently dropped.
    """
    if len(a) != len(b):
        return float("inf")
    if not a:
        return 0.0
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def dedupe_perceptual_indices(
    thumbs: list[Sequence[int]],
    threshold: float = PERCEPTUAL_DEDUP_THRESHOLD,
) -> list[int]:
    """Return the indices of frames to keep, dropping near-duplicates.

    Keeps the first frame, then keeps each subsequent frame only when its
    delta against the last *kept* frame is strictly greater than ``threshold``.
    Comparing against the last kept frame (not the previous one) prevents slow
    visual drift from accumulating unnoticed: a static slide collapses to a
    single capture, while a gradual pan still yields periodic keeps.
    """
    kept: list[int] = []
    last_thumb: Sequence[int] | None = None
    for i, thumb in enumerate(thumbs):
        if last_thumb is None or frame_delta(thumb, last_thumb) > threshold:
            kept.append(i)
            last_thumb = thumb
    return kept


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
    """Determine which timestamps to screenshot (chapters or explicit list).
    Returns list of seconds, or 'ASK_USER' if chapters mode but the video has
    no chapters. Scene mode never enters this function.
    Appends any issues to warnings list.
    """
    if screenshots_arg in ("chapters", "auto"):
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


def get_lowres_stream_url(url: str) -> str | None:
    """Get a low-resolution (<=360p) direct stream URL for the scene-detection
    pass. Detection decodes every frame, so bandwidth matters; the final
    screenshots are still extracted from the <=1080p stream."""
    result = run_ytdlp([
        "-g", "-f", "best[height<=360]/best",
        "--no-playlist", "--no-warnings", url,
    ])
    if result.returncode != 0:
        return None
    lines = result.stdout.strip().split("\n")
    return lines[0] if lines else None


def detect_scene_timestamps(
    url: str,
    threshold: float,
    duration: float,
    warnings: list[str],
) -> list[float]:
    """Pass 1 of scene mode: decode the low-res stream once and return the
    timestamps where ffmpeg's scene score exceeds threshold. Frames are NOT
    written here — extraction happens via extract_screenshots() at <=1080p.

    Returns [] on any failure (caller renders the run with 0 screenshots and
    the warning explains why). A pass that fails with HTTP 403 is retried
    exactly once with a freshly fetched stream URL — YouTube occasionally
    invalidates stream URLs right after issuing them; a fresh yt-dlp fetch
    resolves it (same convention as the documented "stream URL expired"
    edge case for extraction). Each timestamp gets SCENE_SEEK_OFFSET added
    so the later seek lands on the settled new screen, clamped to duration.
    0.0 is prepended so the opening screen is always captured;
    apply_min_gap() collapses it with an early first detection.
    """
    # Detection decodes the whole video; 360p runs several-x realtime, so
    # wall-clock ~= duration is a generous ceiling. Floor 300s, cap 30 min.
    timeout = min(1800, max(300, int(duration or 0)))

    proc = None
    for attempt in (1, 2):
        # Fetch inside the loop: the retry's whole point is a FRESH URL.
        stream_url = get_lowres_stream_url(url)
        if not stream_url:
            msg = "Could not fetch low-res stream URL for scene detection."
            warnings.append(msg)
            print(f"ERROR: {msg}", file=sys.stderr)
            return []

        cmd = [
            "ffmpeg",
            "-hide_banner", "-loglevel", "error",
            "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5",
            "-i", stream_url,
            "-an",
            "-vf", f"select='gt(scene,{threshold})',metadata=print:file=-",
            "-f", "null", "-",
        ]

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            msg = (
                f"Scene detection timed out (>{timeout}s) — re-run with "
                "`--screenshots chapters` or explicit timestamps."
            )
            warnings.append(msg)
            print(f"WARNING: {msg}", file=sys.stderr)
            return []

        if proc.returncode == 0:
            break

        if attempt == 1 and "403" in (proc.stderr or ""):
            print(
                "WARNING: Scene detection got HTTP 403 — retrying once with "
                "a fresh stream URL",
                file=sys.stderr,
            )
            continue

        err = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else "unknown error"
        msg = f"Scene detection failed: {err}"
        warnings.append(msg)
        print(f"WARNING: {msg}", file=sys.stderr)
        return []

    detected = parse_scene_timestamps(proc.stdout)
    offset_applied = [
        min(duration, ts + SCENE_SEEK_OFFSET) if duration else ts + SCENE_SEEK_OFFSET
        for ts in detected
    ]
    return [0.0] + offset_applied


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

        # -y -loglevel BEFORE -ss; -ss BEFORE -i for fast input seeking.
        # Decimal seconds: truncating to int could seek BEFORE a detected
        # scene change and capture the previous screen.
        cmd = [
            "ffmpeg",
            "-y", "-loglevel", "error",
            "-ss", f"{ts:.2f}",
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


def compute_thumbnail(png_path: str, size: int = THUMBNAIL_SIZE) -> list[int] | None:
    """Render a size x size grayscale thumbnail of a PNG as raw pixel values
    via ffmpeg (no PIL dependency). Returns size*size ints (0..255), or None if
    ffmpeg fails or the raw output has the wrong length."""
    cmd = [
        "ffmpeg", "-v", "error",
        "-i", png_path,
        "-vf", f"scale={size}:{size},format=gray",
        "-f", "rawvideo", "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=30)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0 or len(proc.stdout) != size * size:
        return None
    return list(proc.stdout)


def dedupe_screenshots(
    out_dir: str,
    screenshots: list[tuple[float, str]],
    threshold: float = PERCEPTUAL_DEDUP_THRESHOLD,
) -> list[tuple[float, str]]:
    """Drop near-duplicate frames from an extracted screenshot set.

    Builds a 16x16 grayscale thumbnail per file, keeps the perceptually
    distinct ones (see ``dedupe_perceptual_indices``), deletes the dropped PNGs
    from ``out_dir``, and returns the filtered ``[(ts, filename), ...]`` list.
    Fail-open: if any thumbnail can't be built, every frame is kept rather than
    risk dropping a distinct one. Original capture-order filenames are preserved
    (gaps in the NNN prefix are cosmetic).
    """
    if len(screenshots) < 2:
        return screenshots
    thumbs = [compute_thumbnail(os.path.join(out_dir, fn)) for _, fn in screenshots]
    if any(t is None for t in thumbs):
        return screenshots
    keep = set(dedupe_perceptual_indices(thumbs, threshold))
    result: list[tuple[float, str]] = []
    for i, (ts, filename) in enumerate(screenshots):
        if i in keep:
            result.append((ts, filename))
        else:
            try:
                os.remove(os.path.join(out_dir, filename))
            except OSError:
                pass
    return result


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


def run_transcript_only(args: argparse.Namespace) -> None:
    """Lean path: fetch and emit ONLY the raw transcript. No metadata fetch,
    no comments, no screenshots, no summary. Names the output folder by the
    video ID parsed from the URL (falls back to a URL-derived slug).
    """
    url = args.url
    total_stages = 2

    video_id = extract_video_id(url)
    slug = video_id or ("video-" + slugify(url, 40))

    date_str = datetime.date.today().isoformat()
    target = os.path.join(args.output_base, f"yt-extract_{date_str}_{slug}")

    # Collision guard before any work — so a re-run without --force does not
    # emit a stage marker for work it never starts.
    if os.path.isdir(target) and not args.force:
        print(f"FOLDER_EXISTS: {target}", file=sys.stderr, flush=True)
        sys.exit(2)
    os.makedirs(target, exist_ok=True)

    emit_stage(1, total_stages, "Downloading transcript")
    # Pass `slug` (not a fixed literal) as the temp-file discriminator so the
    # VTT temp prefix stays unique per video even when extract_video_id misses.
    transcript, sub_hint, segments = download_and_process_vtt(url, slug)

    emit_stage(2, total_stages, "Writing output")
    sections = [
        # duration is unknown in transcript-only mode (no metadata fetch), so
        # pass 0 — render_transcript_info deliberately omits the long-video hint.
        render_transcript_info(sub_hint, 0),
        render_transcript(transcript, segments, [], []),
    ]
    print("\n".join(section for section in sections if section))

    # Deliberate blank line: OUTPUT_FOLDER: must be the last non-empty stdout
    # line so the skill can parse it.
    print()
    print(f"OUTPUT_FOLDER: {target.replace(os.sep, '/')}")


def main():
    parser = argparse.ArgumentParser(description="Extract YouTube video data")
    parser.add_argument("url", help="YouTube URL")
    parser.add_argument("--comments", action="store_true", help="Also fetch top comments")
    parser.add_argument(
        "--screenshots", nargs="?", const="scenes", default=None,
        help="Extract screenshots. Without value: ffmpeg scene detection "
             "(default threshold 0.04). 'scenes=0.05': custom threshold. "
             "'chapters': chapter markers. Comma-separated timestamps: "
             "0:30,2:15,5:00",
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
    parser.add_argument(
        "--transcript-only", action="store_true",
        help="Fetch and output ONLY the raw transcript — no metadata, "
             "description, chapters, comments, or screenshots. Skips the "
             "metadata fetch; names the output folder by video ID.",
    )
    args = parser.parse_args()

    if args.transcript_only:
        run_transcript_only(args)
        return

    url = args.url

    # --- Screenshot mode (parsed early — affects the stage count) ---
    screenshot_warnings: list[str] = []
    ss_mode: str | None = None
    ss_threshold: float | None = None
    if args.screenshots is not None:
        try:
            ss_mode, ss_threshold = parse_screenshots_mode(args.screenshots)
        except ValueError:
            ss_mode, ss_threshold = "scenes", DEFAULT_SCENE_THRESHOLD
            msg = (
                f"Invalid scene threshold in '{args.screenshots}' — "
                f"using default {DEFAULT_SCENE_THRESHOLD}."
            )
            screenshot_warnings.append(msg)
            print(f"WARNING: {msg}", file=sys.stderr)

    # --- Stage count (adaptive to enabled features) ---
    stages = ["metadata", "transcript"]
    if args.comments:
        stages.append("comments")
    if args.screenshots is not None:
        if ss_mode == "scenes":
            stages.append("scene-detection")
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
    # screenshot_warnings was hoisted above the stage computation so the
    # threshold-parse fallback has a place to report.
    screenshots = []
    screenshot_requested = 0
    screenshot_deduped = 0  # near-duplicates dropped in scenes mode
    screenshot_marker = ""  # "FFMPEG_MISSING" or "SCREENSHOTS_ASK_USER"
    if args.screenshots is not None:
        if not check_ffmpeg():
            # Consume the reserved stage slot(s) so the final marker stays [N/N]
            stage_idx += 2 if ss_mode == "scenes" else 1
            screenshot_marker = "FFMPEG_MISSING"
            screenshot_warnings.append("ffmpeg not found — no screenshots extracted.")
            emit_stage(stage_idx, total_stages, "Screenshots skipped (ffmpeg missing)")
        else:
            if ss_mode == "scenes":
                stage_idx += 1
                emit_stage(stage_idx, total_stages, "Detecting scene changes")
                detected = detect_scene_timestamps(
                    url, ss_threshold, meta["duration"], screenshot_warnings,
                )
                gapped = apply_min_gap(detected)
                timestamps = thin_evenly(gapped)
                if len(gapped) > SCENE_MAX_SCREENSHOTS:
                    screenshot_warnings.append(
                        f"{len(gapped)} scene changes detected — thinned evenly "
                        f"to {SCENE_MAX_SCREENSHOTS}. Raise the threshold for "
                        f"fewer captures (e.g. --screenshots scenes=0.05)."
                    )
                # Success always yields the prepended 0.0, so a single entry
                # means nothing scored above the threshold.
                if detected and len(timestamps) == 1:
                    screenshot_warnings.append(
                        f"No scene changes detected above threshold "
                        f"{ss_threshold} — captured the opening frame only. "
                        f"Try a lower threshold (e.g. --screenshots "
                        f"scenes=0.01) or explicit timestamps."
                    )
            else:
                timestamps = resolve_timestamps(
                    args.screenshots, meta["chapters"], meta["duration"],
                    screenshot_warnings,
                )
            stage_idx += 1
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
                # Scenes mode can fire on near-identical frames (held slides,
                # sub-threshold changes). Drop perceptual duplicates. Explicit
                # chapters/timestamps are intentional, so they are left as-is.
                if ss_mode == "scenes" and len(screenshots) > 1:
                    before = len(screenshots)
                    screenshots = dedupe_screenshots(out_dir, screenshots)
                    screenshot_deduped = before - len(screenshots)
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
            deduped=screenshot_deduped,
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
