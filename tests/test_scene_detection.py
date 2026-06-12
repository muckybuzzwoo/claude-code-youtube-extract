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


# --- parse_screenshots_mode ---


def test_mode_bare_scenes_uses_default_threshold():
    assert yt_extract.parse_screenshots_mode("scenes") == (
        "scenes", yt_extract.DEFAULT_SCENE_THRESHOLD,
    )


def test_mode_scenes_with_explicit_threshold():
    assert yt_extract.parse_screenshots_mode("scenes=0.05") == ("scenes", 0.05)


@pytest.mark.parametrize("arg", ["scenes=abc", "scenes=", "scenes=0", "scenes=1.5", "scenes=-0.1"])
def test_mode_scenes_invalid_threshold_raises(arg):
    with pytest.raises(ValueError):
        yt_extract.parse_screenshots_mode(arg)


def test_mode_threshold_upper_bound_inclusive():
    assert yt_extract.parse_screenshots_mode("scenes=1") == ("scenes", 1.0)


def test_mode_chapters():
    assert yt_extract.parse_screenshots_mode("chapters") == ("chapters", None)


def test_mode_legacy_auto_maps_to_chapters():
    # "auto" was the pre-1.8.0 const value — kept as an alias so direct
    # callers passing it keep the old chapter behavior.
    assert yt_extract.parse_screenshots_mode("auto") == ("chapters", None)


@pytest.mark.parametrize("arg", ["0:30,2:15", "90", "1:30.5,5:00"])
def test_mode_anything_else_is_timestamps(arg):
    assert yt_extract.parse_screenshots_mode(arg) == ("timestamps", None)


# --- parse_scene_timestamps ---

# Verbatim lines from a real `metadata=print:file=-` run (ffmpeg on this
# repo's smoke test) — note pts_time:1 without a decimal part, and that
# scene_score lines must be ignored.
FFMPEG_METADATA_FIXTURE = """\
frame:0    pts:1024    pts_time:0.0666667
lavfi.scene_score=0.090931
frame:7    pts:15360   pts_time:1
lavfi.scene_score=0.055059
frame:10   pts:21504   pts_time:1.4
lavfi.scene_score=0.064512
"""


def test_parse_scene_timestamps_fixture():
    assert yt_extract.parse_scene_timestamps(FFMPEG_METADATA_FIXTURE) == [
        0.0666667, 1.0, 1.4,
    ]


def test_parse_scene_timestamps_returns_sorted():
    out_of_order = "frame:1 pts:2 pts_time:9.5\nframe:0 pts:1 pts_time:3.25\n"
    assert yt_extract.parse_scene_timestamps(out_of_order) == [3.25, 9.5]


@pytest.mark.parametrize("garbage", ["", "no matches here", "pts_time:abc\nlavfi.scene_score=0.5"])
def test_parse_scene_timestamps_garbage_input(garbage):
    assert yt_extract.parse_scene_timestamps(garbage) == []


# --- apply_min_gap ---


def test_min_gap_keeps_first_of_cluster():
    assert yt_extract.apply_min_gap([10.0, 11.0, 12.0, 20.0], min_gap=4.0) == [10.0, 20.0]


def test_min_gap_empty_and_single():
    assert yt_extract.apply_min_gap([], min_gap=4.0) == []
    assert yt_extract.apply_min_gap([5.0], min_gap=4.0) == [5.0]


def test_min_gap_sorts_defensively():
    assert yt_extract.apply_min_gap([20.0, 10.0, 11.0], min_gap=4.0) == [10.0, 20.0]


def test_min_gap_exact_boundary_is_kept():
    # Exactly min_gap apart counts as far enough (>= comparison).
    assert yt_extract.apply_min_gap([0.0, 4.0, 8.0], min_gap=4.0) == [0.0, 4.0, 8.0]


# --- thin_evenly ---


def test_thin_evenly_small_list_unchanged():
    ts = [float(i) for i in range(50)]
    assert yt_extract.thin_evenly(ts, max_count=50) == ts


def test_thin_evenly_reduces_to_max_count():
    ts = [float(i) for i in range(127)]
    thinned = yt_extract.thin_evenly(ts, max_count=50)
    assert len(thinned) == 50
    assert thinned[0] == 0.0
    assert thinned[-1] == 126.0
    assert thinned == sorted(thinned)
    assert len(set(thinned)) == len(thinned)


def test_thin_evenly_uses_module_default_cap():
    ts = [float(i) for i in range(200)]
    assert len(yt_extract.thin_evenly(ts)) == yt_extract.SCENE_MAX_SCREENSHOTS
