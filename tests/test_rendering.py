import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "yt-extract.py"
if not MODULE_PATH.exists():
    raise FileNotFoundError(
        f"Expected source module at {MODULE_PATH} — is the test suite "
        "running from the repo root?"
    )
spec = importlib.util.spec_from_file_location("yt_extract", MODULE_PATH)
if spec is None or spec.loader is None:
    raise ImportError(f"Could not build import spec for {MODULE_PATH}")
yt_extract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(yt_extract)


# --- slugify ---


def test_slugify_basic_behavior():
    assert yt_extract.slugify("Hello, World!") == "hello-world"
    assert yt_extract.slugify("A" * 60) == "a" * 50


def test_slugify_strips_symbols_keeps_unicode_letters():
    # Python's \w matches Unicode letters by default, so accented characters
    # survive — slugify deliberately does NOT ASCII-fold ("Café" → "café",
    # not "cafe"). Symbols/emoji are stripped. Callers that need ASCII
    # output should compose an extra fold step.
    assert yt_extract.slugify("Café ☕") == "café"


def test_slugify_empty_and_whitespace_inputs():
    assert yt_extract.slugify("") == ""
    assert yt_extract.slugify("   ") == ""


def test_slugify_collapses_dashes_and_replaces_underscores():
    assert yt_extract.slugify("hello--world") == "hello-world"
    assert yt_extract.slugify("hello_world") == "hello-world"


def test_slugify_strips_trailing_dash_after_truncation():
    # "a-" * 30 is 60 chars — forces truncation to land on a dash.
    # Contract, not implementation shape: result respects max_length, has no
    # trailing dash, and preserves the leading slug content.
    result = yt_extract.slugify("a-" * 30)
    assert len(result) <= 50
    assert not result.endswith("-")
    assert result.startswith("a-a-")


# --- timestamp formatters ---


def test_timestamp_formatters_and_parser():
    assert yt_extract.format_timestamp_display(65) == "1:05"
    assert yt_extract.format_timestamp_display(3723) == "1:02:03"
    assert yt_extract.format_timestamp_filename(65) == "01m05s"
    assert yt_extract.format_timestamp_filename(3723) == "1h02m03s"
    assert yt_extract.parse_timestamp("1:05") == 65
    assert yt_extract.parse_timestamp("1:02:03") == 3723


def test_format_timestamp_display_boundaries():
    assert yt_extract.format_timestamp_display(0) == "0:00"
    assert yt_extract.format_timestamp_display(1) == "0:01"
    assert yt_extract.format_timestamp_display(59) == "0:59"
    assert yt_extract.format_timestamp_display(3600) == "1:00:00"
    assert yt_extract.format_timestamp_display(36000) == "10:00:00"


def test_format_timestamp_display_truncates_fractional_seconds():
    assert yt_extract.format_timestamp_display(65.9) == "1:05"


def test_format_timestamp_filename_boundaries():
    assert yt_extract.format_timestamp_filename(0) == "00m00s"
    assert yt_extract.format_timestamp_filename(3600) == "1h00m00s"


# --- parse_timestamp ---


def test_parse_timestamp_boundaries_and_formats():
    assert yt_extract.parse_timestamp("0:00") == 0.0
    assert yt_extract.parse_timestamp("23:59:59") == 86399.0
    assert yt_extract.parse_timestamp("1:30.5") == 90.5
    assert yt_extract.parse_timestamp("120") == 120.0
    assert yt_extract.parse_timestamp("120.5") == 120.5


def test_parse_timestamp_raises_on_invalid():
    with pytest.raises(ValueError):
        yt_extract.parse_timestamp("not-a-timestamp")
    with pytest.raises(ValueError):
        yt_extract.parse_timestamp("1:2:3:4")


# --- render_transcript_info ---


def test_render_transcript_info_uses_integer_minutes_for_long_videos():
    rendered = yt_extract.render_transcript_info("manual (en)", 3723.9)
    assert rendered == "### Transcript Info\nmanual (en)\nVideo is 62 min long — full transcript\n"


# --- render_screenshots_section ---


def test_render_screenshots_section_with_chapter_titles():
    rendered = yt_extract.render_screenshots_section(
        True,
        "",
        [(30, "001_00m30s_intro.png")],
        [{"start_time": 0, "end_time": 60, "title": "Intro"}],
        120,
    )
    assert rendered == (
        "### Screenshots\n"
        "- ![0:30 — Intro](screenshots/001_00m30s_intro.png) 0:30 — Intro\n"
    )


def test_render_screenshots_section_disabled_returns_empty_string():
    assert yt_extract.render_screenshots_section(False, "", [], [], 0) == ""


def test_render_screenshots_section_ffmpeg_missing_marker():
    rendered = yt_extract.render_screenshots_section(True, "FFMPEG_MISSING", [], [], 120)
    assert rendered == "### Screenshots\nFFMPEG_MISSING\n"


def test_render_screenshots_section_ask_user_marker_includes_duration():
    rendered = yt_extract.render_screenshots_section(
        True, "SCREENSHOTS_ASK_USER", [], [], 120
    )
    assert rendered == (
        "### Screenshots\nSCREENSHOTS_ASK_USER\nvideo_duration: 120\n"
    )


def test_render_screenshots_section_without_chapters_uses_simple_format():
    rendered = yt_extract.render_screenshots_section(
        True, "", [(30, "001_00m30s.png")], [], 120
    )
    assert rendered == (
        "### Screenshots\n- ![0:30](screenshots/001_00m30s.png) 0:30\n"
    )


def test_render_screenshots_section_empty_screenshots_enabled():
    assert yt_extract.render_screenshots_section(True, "", [], [], 120) == "### Screenshots\n"


# --- render_screenshot_status ---


def test_render_screenshot_status_success_and_warning():
    rendered = yt_extract.render_screenshot_status(
        True,
        "",
        2,
        [(30, "001.png")],
        ["Frame at 1:00 failed: timeout"],
    )
    assert rendered == (
        "### Screenshot Status\n"
        "2 screenshots requested, 1 successfully extracted.\n"
        "- WARNING: Frame at 1:00 failed: timeout\n"
    )


def test_render_screenshot_status_disabled_returns_empty_string():
    assert yt_extract.render_screenshot_status(False, "", 0, [], []) == ""


def test_render_screenshot_status_marker_skips_count_line():
    rendered = yt_extract.render_screenshot_status(True, "FFMPEG_MISSING", 2, [], [])
    assert rendered == "### Screenshot Status\nFFMPEG_MISSING\n"


def test_render_screenshot_status_zero_requested_skips_count():
    assert yt_extract.render_screenshot_status(True, "", 0, [], []) == "### Screenshot Status\n"


def test_render_screenshot_status_full_success_no_warnings():
    rendered = yt_extract.render_screenshot_status(
        True, "", 2, [(30, "a.png"), (60, "b.png")], []
    )
    assert rendered == (
        "### Screenshot Status\n"
        "2 screenshots requested, 2 successfully extracted.\n"
    )


def test_render_screenshot_status_multiple_warnings():
    rendered = yt_extract.render_screenshot_status(
        True, "", 3, [(30, "a.png")], ["First failed", "Second failed"],
    )
    assert rendered == (
        "### Screenshot Status\n"
        "3 screenshots requested, 1 successfully extracted.\n"
        "- WARNING: First failed\n"
        "- WARNING: Second failed\n"
    )


# --- render_comments ---


def test_render_comments_modes():
    assert yt_extract.render_comments(False, []) == "### Comments\nSKIPPED"
    assert yt_extract.render_comments(True, []) == "### Comments\nComments not available."
    assert yt_extract.render_comments(True, [{"author": "Alice", "likes": 4, "text": "Useful"}]) == (
        "### Comments\n1. **Alice** (👍 4) — Useful"
    )


def test_render_comments_numbers_multiple_comments_sequentially():
    rendered = yt_extract.render_comments(True, [
        {"author": "Alice", "likes": 4, "text": "First"},
        {"author": "Bob", "likes": 2, "text": "Second"},
        {"author": "Carol", "likes": 0, "text": "Third"},
    ])
    assert rendered == (
        "### Comments\n"
        "1. **Alice** (👍 4) — First\n"
        "2. **Bob** (👍 2) — Second\n"
        "3. **Carol** (👍 0) — Third"
    )
