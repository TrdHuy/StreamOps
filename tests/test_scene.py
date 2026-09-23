from pathlib import Path

import pytest

from streamops.errors import StreamOpsError
from streamops.scene import apply_scene, verify_scene

from .fake_obs import FakeObsClient


ROOT = Path(__file__).resolve().parents[1]
DESKTOP_SOURCE = "StreamOps Desktop POC"
CLOCK_SOURCE = "StreamOps Clock POC"


def test_apply_creates_scene_and_is_idempotent() -> None:
    obs = FakeObsClient()

    first = apply_scene("gaming-poc", client=obs, root=ROOT)
    second = apply_scene("gaming-poc", client=obs, root=ROOT)

    assert first.changed is True
    assert second.changed is False
    assert [item["sourceName"] for item in obs.scenes["gaming-poc"]] == [DESKTOP_SOURCE, CLOCK_SOURCE]
    assert [item["inputName"] for item in obs.inputs] == [DESKTOP_SOURCE, CLOCK_SOURCE]
    assert obs.video_settings["baseWidth"] == 3840
    assert obs.video_settings["fpsNumerator"] == 30


def test_apply_repairs_wrong_transform() -> None:
    obs = FakeObsClient()
    apply_scene("gaming-poc", client=obs, root=ROOT)
    overlay_id = next(
        int(item["sceneItemId"])
        for item in obs.scenes["gaming-poc"]
        if item["sourceName"] == CLOCK_SOURCE
    )
    obs.transforms[overlay_id]["positionX"] = 123

    result = apply_scene("gaming-poc", client=obs, root=ROOT)

    assert result.changed is True
    assert obs.transforms[overlay_id]["positionX"] == 3760


def test_apply_removes_duplicate_configured_items_only() -> None:
    obs = FakeObsClient()
    obs.create_scene("gaming-poc")
    obs.create_input("gaming-poc", DESKTOP_SOURCE, "monitor_capture", {}, enabled=True)
    obs.create_scene_item("gaming-poc", DESKTOP_SOURCE)
    obs.inputs.append({"inputName": "Unmanaged", "inputKind": "browser_source"})
    obs.create_scene_item("gaming-poc", "Unmanaged")

    apply_scene("gaming-poc", client=obs, root=ROOT)

    names = [item["sourceName"] for item in obs.scenes["gaming-poc"]]
    assert names.count(DESKTOP_SOURCE) == 1
    assert "Unmanaged" in names


def test_verify_passes_after_apply() -> None:
    obs = FakeObsClient()
    apply_scene("gaming-poc", client=obs, root=ROOT)

    result = verify_scene("gaming-poc", client=obs, root=ROOT)

    assert result.status == "PASS"


def test_verify_fails_when_managed_input_settings_drift() -> None:
    obs = FakeObsClient()
    apply_scene("gaming-poc", client=obs, root=ROOT)
    obs.input_settings[CLOCK_SOURCE]["height"] = 100

    result = verify_scene("gaming-poc", client=obs, root=ROOT)

    assert result.status == "FAIL"
    assert any(check.id == "source.overlay.settings" and check.status == "FAIL" for check in result.checks)


def test_apply_refuses_video_setting_change_while_recording() -> None:
    obs = FakeObsClient()
    obs.recording = True

    with pytest.raises(StreamOpsError, match="streaming or recording is active"):
        apply_scene("gaming-poc", client=obs, root=ROOT)


def test_apply_preflights_managed_input_kind_before_video_mutation() -> None:
    obs = FakeObsClient()
    obs.input_kinds = ["monitor_capture"]
    original_video_settings = dict(obs.video_settings)

    with pytest.raises(StreamOpsError, match="browser_source"):
        apply_scene("gaming-poc", client=obs, root=ROOT)

    assert obs.video_settings == original_video_settings


def test_apply_handles_existing_source_with_zero_runtime_size() -> None:
    obs = FakeObsClient()

    first = apply_scene("gaming-poc", client=obs, root=ROOT)
    overlay_id = next(
        int(item["sceneItemId"])
        for item in obs.scenes["gaming-poc"]
        if item["sourceName"] == CLOCK_SOURCE
    )
    obs.transforms[overlay_id]["sourceWidth"] = 0
    obs.transforms[overlay_id]["sourceHeight"] = 0
    second = apply_scene("gaming-poc", client=obs, root=ROOT)

    assert first.changed is True
    assert second.changed is False
    assert obs.transforms[overlay_id]["boundsType"] == "OBS_BOUNDS_SCALE_TO_WIDTH"
    assert obs.transforms[overlay_id]["boundsWidth"] == 845.0
    assert obs.transforms[overlay_id]["boundsHeight"] == 1.0


def test_apply_reconciles_managed_input_settings() -> None:
    obs = FakeObsClient()
    apply_scene("gaming-poc", client=obs, root=ROOT)
    obs.input_settings[CLOCK_SOURCE]["width"] = 320

    result = apply_scene("gaming-poc", client=obs, root=ROOT)

    assert result.changed is True
    assert obs.input_settings[CLOCK_SOURCE]["width"] == 845


def test_apply_refuses_existing_managed_source_with_wrong_kind_before_video_mutation() -> None:
    obs = FakeObsClient()
    obs.inputs.append(
        {
            "inputName": CLOCK_SOURCE,
            "inputKind": "monitor_capture",
            "unversionedInputKind": "monitor_capture",
        }
    )
    original_video_settings = dict(obs.video_settings)

    with pytest.raises(StreamOpsError, match="already exists with input kind"):
        apply_scene("gaming-poc", client=obs, root=ROOT)

    assert obs.video_settings == original_video_settings
