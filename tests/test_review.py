from pathlib import Path

from streamops.review import review_scene
from streamops.scene import apply_scene

from .fake_obs import FakeObsClient


ROOT = Path(__file__).resolve().parents[1]


def test_review_writes_pass_artifacts(tmp_path: Path) -> None:
    obs = FakeObsClient()
    apply_scene("gaming-poc", client=obs, root=ROOT)

    result = review_scene("gaming-poc", client=obs, root=ROOT, artifact_root=tmp_path)

    assert result.status == "PASS"
    assert Path(result.artifacts["preview"]).exists()
    assert Path(result.artifacts["verify"]).exists()
    assert Path(result.artifacts["report"]).exists()


def test_review_video_refusal_is_reported(tmp_path: Path) -> None:
    obs = FakeObsClient()
    apply_scene("gaming-poc", client=obs, root=ROOT)
    obs.streaming = True

    result = review_scene("gaming-poc", client=obs, root=ROOT, artifact_root=tmp_path, video_seconds=15)

    assert result.status == "FAIL"
    assert Path(result.artifacts["verify"]).exists()
    assert Path(result.artifacts["report"]).exists()
    assert any(check.id == "artifact.video" for check in result.checks)


def test_review_video_is_copied_into_artifacts(tmp_path: Path) -> None:
    obs = FakeObsClient()
    obs.recording_output_path = tmp_path / "obs-recording.mp4"
    apply_scene("gaming-poc", client=obs, root=ROOT)

    result = review_scene("gaming-poc", client=obs, root=ROOT, artifact_root=tmp_path, video_seconds=1)

    video_path = Path(result.artifacts["video"])
    assert result.status == "PASS"
    assert video_path.exists()
    assert video_path.name == "sample-1s.mp4"
    assert video_path.parent.parent == tmp_path / "gaming-poc"
    assert result.artifacts["video_source"] == str(obs.recording_output_path)
