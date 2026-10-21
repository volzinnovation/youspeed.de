"""Corpus extraction invariants; generated movies only, no device or network."""
from fractions import Fraction
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from scripts.lanes import prime_video_corpus as corpus


def config(tmp_path):
    source = tmp_path / "source.avi"
    source.write_bytes(b"immutable-source")
    return {"sources": {"camera": {"path": str(source), "sha256": corpus.sha(source),
                                   "driveGroup": "drive-a", "split": "development"}},
            "clips": [{"id": "first", "source": "camera", "start": 0, "end": 1, "tags": []}]}


def test_bad_hash_fails_before_probe_and_output(tmp_path, monkeypatch):
    data = config(tmp_path)
    data["sources"]["camera"]["sha256"] = "0" * 64
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data))
    monkeypatch.setattr(corpus, "probe", lambda *args: pytest.fail("Probe ran before hash verification"))
    with pytest.raises(ValueError, match="content hash"):
        corpus.prime(path, tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("case", ["same_source", "content_alias", "duplicate_id"])
def test_overlap_and_duplicates_rejected(tmp_path, case):
    data = config(tmp_path)
    second = dict(data["clips"][0], id="second", start=.5, end=1.5)
    if case == "content_alias":
        data["sources"]["alias"] = dict(data["sources"]["camera"])
        second["source"] = "alias"
    elif case == "duplicate_id":
        second.update(id="first", start=1, end=2)
    data["clips"].append(second)
    with pytest.raises(ValueError, match="Overlapping|duplicate"):
        corpus.validate(data, tmp_path)


@pytest.mark.parametrize("case", ["source", "content", "driveGroup"])
def test_split_leakage_rejected(tmp_path, case):
    data = config(tmp_path)
    other = tmp_path / "other.avi"
    other.write_bytes(b"different-source")
    if case == "source":
        sid = "camera"
    else:
        sid = "other"
        data["sources"][sid] = dict(data["sources"]["camera"], split="acceptance")
        if case == "driveGroup":
            data["sources"][sid].update(path=str(other), sha256=corpus.sha(other))
        else:
            data["sources"][sid]["driveGroup"] = "drive-b"
    data["clips"].append(dict(id="second", source=sid, split="acceptance", start=1, end=2))
    with pytest.raises(ValueError, match="Cross-split"):
        corpus.validate(data, tmp_path)


def test_adjacent_clips_and_unknown_routes_are_not_invented(tmp_path):
    data = config(tmp_path)
    data["sources"]["camera"].pop("split")
    data["sources"]["camera"]["routeGroup"] = None
    data["clips"].append(dict(id="next", source="camera", start=1, end=2))
    sources, clips = corpus.validate(data, tmp_path)
    assert all(clip["split"] == "development" for clip in clips)
    assert sources["camera"]["routeGroup"] is None


def test_original_pts_separate_from_target_and_bounded_support():
    rows = [{"pts": value} for value in (10, 14, 21, 24, 30)]
    selected = corpus.select_frames(rows, Fraction(1, 100), Fraction(31, 100),
                                    dict(id="vfr", start=.1, end=.3), Fraction(10))
    assert selected == [(0, Fraction(1, 10)), (2, Fraction(1, 5))]
    assert rows[selected[1][0]]["pts"] * Fraction(1, 100) != selected[1][1]
    with pytest.raises(ValueError, match="coverage"):
        corpus.select_frames(rows, Fraction(1, 100), Fraction(31, 100),
                             dict(id="eof", start=.1, end=.4), Fraction(10))
    diagnostics = {}
    sparse = corpus.select_frames([{"pts": 0}, {"pts": 15}, {"pts": 35}], Fraction(1, 100), Fraction(1),
                                  dict(id="variable-cadence", start=0, end=.4), Fraction(10), diagnostics)
    assert sparse == [(0, Fraction(0)), (1, Fraction(1, 10)), (2, Fraction(1, 5))]
    assert diagnostics["skippedTargetTimes"] == [.3]
    assert diagnostics["maximumTargetDelaySeconds"] == .15


def test_packet_b_frames_sorted_by_presentation_not_dts():
    packets = [{"pts": 0, "dts": -2, "duration": 1},
               {"pts": 3, "dts": -1, "duration": 1},
               {"pts": 1, "dts": 0, "duration": 1},
               {"pts": 2, "dts": 1, "duration": 1}]
    rows = corpus.presentation_table(packets, dict(width=320, height=180), "packets")
    assert [row["pts"] for row in rows] == [0, 1, 2, 3]
    assert all(row["width"] == 320 for row in rows)


@pytest.mark.parametrize("packets", [
    [{"pts": 0, "duration": 1}, {"pts": 0, "duration": 1}],
    [{"duration": 1}], [{"pts": float("nan"), "duration": 1}],
    [{"pts": 0}], [{"pts": 0, "duration": 0}],
    [{"pts": 0, "duration": -1}], [{"pts": 0, "duration": float("inf")}],
])
def test_invalid_packet_timing_rejected(packets):
    with pytest.raises(ValueError, match="PTS|pts|duration"):
        corpus.presentation_table(packets, dict(width=320, height=180), "packets")


def test_center_nearest_gray_preserves_aspect():
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    bgr = np.arange(180 * 400 * 3, dtype=np.uint8).reshape(180, 400, 3)
    gray = corpus.center_gray(bgr)
    assert gray.shape == (172, 384)
    xs = ((np.arange(384) + .5) * 400 / 384).astype(int)
    ys = ((np.arange(172) + .5) * 180 / 172).astype(int)
    assert np.array_equal(gray, cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)[np.ix_(ys, xs)])


def test_negative_initial_sentinel_does_not_shift_later_pts():
    samples = [dict(encodedTime=0, decoderTime=-1 / 600, ignoredInitialSentinel=True)]
    samples += [dict(encodedTime=t / 30, decoderTime=t / 30) for t in range(1, 6)]
    assert corpus.decode_clock_offset(samples, Fraction(1, 600)) == 0


def test_multiple_initial_frames_verify_relative_clock_offset():
    samples = [dict(encodedTime=10 + t / 30, decoderTime=t / 30) for t in range(6)]
    assert corpus.decode_clock_offset(samples, Fraction(1, 600)) == 10


@pytest.mark.parametrize("case", ["one_tick_shift", "duplicate", "nonfinite", "too_few"])
def test_unreliable_decode_clock_is_rejected(case):
    samples = [dict(encodedTime=t / 30, decoderTime=t / 30) for t in range(6)]
    if case == "one_tick_shift":
        samples[3]["decoderTime"] += 1 / 600
    elif case == "duplicate":
        samples[3]["decoderTime"] = samples[2]["decoderTime"]
    elif case == "nonfinite":
        samples[3]["decoderTime"] = float("nan")
    else:
        samples = samples[:2]
    with pytest.raises(ValueError, match="clock|timestamp"):
        corpus.decode_clock_offset(samples, Fraction(1, 600))


@pytest.fixture
def movie(tmp_path):
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    if not shutil.which("ffprobe"):
        pytest.skip("ffprobe is required for encoded-timestamp integration")
    check = subprocess.run(["ffprobe", "-version"], capture_output=True)
    if check.returncode:
        pytest.skip("ffprobe installation is not runnable")
    path = tmp_path / "synthetic.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 20, (320, 180))
    if not writer.isOpened():
        pytest.skip("OpenCV MJPG encoder unavailable")
    for frame in range(24):
        image = np.zeros((180, 320, 3), np.uint8)
        image[:, :160] = (frame * 5, 40, 220)
        image[:, 160:] = (180, 70, frame * 5)
        writer.write(image)
    writer.release()
    data = {"sources": {"synthetic": {"path": str(path), "sha256": corpus.sha(path),
                                      "driveGroup": "synthetic", "provenance": {"kind": "generated_test"}}},
            "clips": [{"id": "clip", "source": "synthetic", "start": .22, "end": .82}]}
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(data))
    return config_path


def test_synthetic_video_hashes_native_manifest_and_pts(movie, tmp_path):
    out = tmp_path / "new-corpus"
    result = corpus.prime(movie, out, sample_every=2)
    assert result["frames"] == 6
    manifest = json.loads((out / "manifest.json").read_text())
    times = [frame["time"] for frame in manifest["frames"]]
    assert times == sorted(set(times))
    assert times[0] == .25
    assert manifest["frames"][0]["targetTime"] == .22
    for frame in manifest["frames"]:
        assert .22 <= frame["time"] < .82
        assert corpus.sha(frame["grayPath"]) == frame["graySha256"]
        assert corpus.sha(frame["rgbPath"]) == frame["rgbSha256"]
        assert Path(frame["grayPath"]).stat().st_size == frame["width"] * frame["height"]
        assert frame["rgbWidth"] <= 960
        assert abs(frame["decoderReportedTime"] - frame["actualPTS"]) <= frame["decodeTimestampToleranceSeconds"]
    # Exercise the actual native replay input validator rather than mirroring it.
    from scripts.lanes.replay_recorded_pipeline import normalized_manifest
    normalized = normalized_manifest(out / "manifest.json", "test")
    assert len(normalized["frames"]) == 6
    with pytest.raises(ValueError, match="exists"):
        corpus.prime(movie, out)


def test_truncated_requested_coverage_never_publishes_manifest(movie, tmp_path):
    data = json.loads(movie.read_text())
    data["clips"][0]["end"] = 2
    movie.write_text(json.dumps(data))
    out = tmp_path / "incomplete"
    with pytest.raises(ValueError, match="coverage"):
        corpus.prime(movie, out)
    assert (out / "failure.json").exists()
    assert not (out / "manifest.json").exists()


def test_decoder_seek_failure_is_not_a_success(movie, tmp_path, monkeypatch):
    cv2 = pytest.importorskip("cv2")
    original = cv2.VideoCapture

    class BadSeek:
        def __init__(self, *args):
            self.cap = original(*args)

        def __getattr__(self, name):
            return getattr(self.cap, name)

        def set(self, key, value):
            return False if key == cv2.CAP_PROP_POS_MSEC else self.cap.set(key, value)

    monkeypatch.setattr(cv2, "VideoCapture", BadSeek)
    out = tmp_path / "bad-seek"
    with pytest.raises(ValueError, match="Seek failed"):
        corpus.prime(movie, out)
    assert not (out / "manifest.json").exists()
