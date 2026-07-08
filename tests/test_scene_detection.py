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


# --- frame_delta (perceptual frame-dedup, adoption #1) ---


def test_frame_delta_identical_is_zero():
    assert yt_extract.frame_delta([10, 20, 30], [10, 20, 30]) == 0.0


def test_frame_delta_uniform_offset_is_that_offset():
    # Every pixel differs by 2 -> mean absolute difference is 2.0.
    assert yt_extract.frame_delta([0, 0], [2, 2]) == 2.0


def test_frame_delta_averages_over_pixels():
    # |0-0| + |10-0| = 10, averaged over 2 pixels -> 5.0.
    assert yt_extract.frame_delta([0, 10], [0, 0]) == 5.0


def test_frame_delta_length_mismatch_is_infinite():
    # Different-sized thumbnails can't be compared -> treat as "definitely
    # different" so the caller keeps the frame rather than dropping it.
    assert yt_extract.frame_delta([1, 2, 3], [1, 2]) == float("inf")


def test_frame_delta_both_empty_is_zero():
    assert yt_extract.frame_delta([], []) == 0.0


# --- dedupe_perceptual_indices ---


def test_dedupe_empty_returns_empty():
    assert yt_extract.dedupe_perceptual_indices([], threshold=2.0) == []


def test_dedupe_single_frame_kept():
    assert yt_extract.dedupe_perceptual_indices([[5]], threshold=2.0) == [0]


def test_dedupe_all_identical_keeps_only_first():
    thumbs = [[7], [7], [7], [7]]
    assert yt_extract.dedupe_perceptual_indices(thumbs, threshold=2.0) == [0]


def test_dedupe_distinct_frames_all_kept():
    thumbs = [[0], [100], [0], [100]]
    assert yt_extract.dedupe_perceptual_indices(thumbs, threshold=2.0) == [0, 1, 2, 3]


def test_dedupe_compares_against_last_kept_not_last_seen():
    # Gradual drift: each frame is only 1 apart from its predecessor, but the
    # comparison is against the last KEPT frame. 0 kept; 1 (delta 1) drop;
    # 2 (delta 2, not > 2) drop; 3 (delta 3 vs frame 0) kept.
    thumbs = [[0], [1], [2], [3]]
    assert yt_extract.dedupe_perceptual_indices(thumbs, threshold=2.0) == [0, 3]


def test_dedupe_threshold_boundary_is_dropped():
    # Exactly at threshold counts as a near-duplicate (keep only if strictly
    # greater), matching "mean-abs-diff <= threshold -> dropped".
    assert yt_extract.dedupe_perceptual_indices([[0], [2]], threshold=2.0) == [0]


def test_dedupe_uses_module_default_threshold():
    # Delta of 1.0 is below the default 2.0 -> second frame dropped.
    assert yt_extract.dedupe_perceptual_indices([[0], [1]]) == [0]
    assert yt_extract.PERCEPTUAL_DEDUP_THRESHOLD == 2.0
