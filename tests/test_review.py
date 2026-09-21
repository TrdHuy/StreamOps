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
