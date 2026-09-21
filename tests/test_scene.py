from pathlib import Path

import pytest

from streamops.errors import StreamOpsError
from streamops.scene import apply_scene, verify_scene

from .fake_obs import FakeObsClient


ROOT = Path(__file__).resolve().parents[1]


def test_apply_creates_scene_and_is_idempotent() -> None:
    obs = FakeObsClient()

    first = apply_scene("gaming-poc", client=obs, root=ROOT)
    second = apply_scene("gaming-poc", client=obs, root=ROOT)

    assert first.changed is True
    assert second.changed is False
    assert [item["sourceName"] for item in obs.scenes["gaming-poc"]] == ["SRC-D4", "OpenStream V8"]
    assert obs.video_settings["baseWidth"] == 3840
    assert obs.video_settings["fpsNumerator"] == 30


def test_apply_repairs_wrong_transform() -> None:
    obs = FakeObsClient()
    apply_scene("gaming-poc", client=obs, root=ROOT)
    camera_id = next(
        int(item["sceneItemId"])
        for item in obs.scenes["gaming-poc"]
        if item["sourceName"] == "OpenStream V8"
    )
    obs.transforms[camera_id]["positionX"] = 123

    result = apply_scene("gaming-poc", client=obs, root=ROOT)

    assert result.changed is True
    assert obs.transforms[camera_id]["positionX"] == 3760


def test_apply_removes_duplicate_configured_items_only() -> None:
    obs = FakeObsClient()
    obs.create_scene("gaming-poc")
    obs.create_scene_item("gaming-poc", "SRC-D4")
    obs.create_scene_item("gaming-poc", "SRC-D4")
    obs.inputs.append({"inputName": "Unmanaged"})
    obs.create_scene_item("gaming-poc", "Unmanaged")

    apply_scene("gaming-poc", client=obs, root=ROOT)

    names = [item["sourceName"] for item in obs.scenes["gaming-poc"]]
    assert names.count("SRC-D4") == 1
    assert "Unmanaged" in names


def test_verify_passes_after_apply() -> None:
    obs = FakeObsClient()
    apply_scene("gaming-poc", client=obs, root=ROOT)

    result = verify_scene("gaming-poc", client=obs, root=ROOT)

    assert result.status == "PASS"


def test_apply_refuses_video_setting_change_while_recording() -> None:
    obs = FakeObsClient()
    obs.recording = True

    with pytest.raises(StreamOpsError, match="streaming or recording is active"):
        apply_scene("gaming-poc", client=obs, root=ROOT)
