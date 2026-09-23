from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from streamops.errors import StreamOpsError


class FakeObsClient:
    def __init__(self) -> None:
        self.version = {"obsVersion": "fake-obs"}
        self.video_settings = {
            "baseWidth": 1920,
            "baseHeight": 1080,
            "outputWidth": 1920,
            "outputHeight": 1080,
            "fpsNumerator": 60,
            "fpsDenominator": 1,
        }
        self.input_kinds = ["monitor_capture", "browser_source"]
        self.inputs: list[dict[str, Any]] = []
        self.input_settings: dict[str, dict[str, Any]] = {}
        self.scenes: dict[str, list[dict[str, Any]]] = {}
        self.transforms: dict[int, dict[str, Any]] = {}
        self.next_item_id = 1
        self.current_scene = "Scene"
        self.recording = False
        self.streaming = False
        self.saved_screenshots: list[Path] = []
        self.recording_output_path: Path | None = None

    def close(self) -> None:
        pass

    def get_version(self) -> dict[str, Any]:
        return self.version

    def get_video_settings(self) -> dict[str, Any]:
        return deepcopy(self.video_settings)

    def set_video_settings(self, settings: dict[str, Any]) -> None:
        self.video_settings.update(settings)

    def get_scene_list(self) -> list[dict[str, Any]]:
        return [{"sceneName": name} for name in self.scenes]

    def create_scene(self, scene_name: str) -> None:
        self.scenes.setdefault(scene_name, [])

    def get_input_list(self) -> list[dict[str, Any]]:
        return deepcopy(self.inputs)

    def get_input_kind_list(self) -> list[str]:
        return list(self.input_kinds)

    def create_input(
        self,
        scene_name: str,
        input_name: str,
        input_kind: str,
        input_settings: dict[str, Any],
        *,
        enabled: bool = True,
    ) -> int:
        self.inputs.append(
            {
                "inputName": input_name,
                "inputKind": input_kind,
                "unversionedInputKind": input_kind,
            }
        )
        self.input_settings[input_name] = deepcopy(input_settings)
        return self.create_scene_item(scene_name, input_name, enabled=enabled)

    def get_input_settings(self, input_name: str) -> dict[str, Any]:
        return deepcopy(self.input_settings.get(input_name, {}))

    def set_input_settings(self, input_name: str, settings: dict[str, Any], *, overlay: bool = True) -> None:
        if overlay:
            self.input_settings.setdefault(input_name, {}).update(deepcopy(settings))
        else:
            self.input_settings[input_name] = deepcopy(settings)

    def get_scene_item_list(self, scene_name: str) -> list[dict[str, Any]]:
        return deepcopy(self.scenes.get(scene_name, []))

    def create_scene_item(self, scene_name: str, source_name: str, *, enabled: bool = True) -> int:
        scene_item_id = self.next_item_id
        self.next_item_id += 1
        item = {
            "sceneItemId": scene_item_id,
            "sourceName": source_name,
            "sceneItemEnabled": enabled,
            "sceneItemIndex": len(self.scenes.setdefault(scene_name, [])),
        }
        self.scenes[scene_name].append(item)
        settings = self.input_settings.get(source_name, {})
        source_width = int(settings.get("width", 3840 if "Desktop" in source_name else 1920))
        source_height = int(settings.get("height", 2160 if "Desktop" in source_name else 1080))
        self.transforms[scene_item_id] = {
            "sourceWidth": source_width,
            "sourceHeight": source_height,
            "alignment": 5,
            "positionX": 0,
            "positionY": 0,
            "scaleX": 1,
            "scaleY": 1,
            "rotation": 0,
            "cropLeft": 0,
            "cropRight": 0,
            "cropTop": 0,
            "cropBottom": 0,
            "boundsType": "OBS_BOUNDS_NONE",
            "boundsAlignment": 5,
            "boundsWidth": 0,
            "boundsHeight": 0,
        }
        return scene_item_id

    def remove_scene_item(self, scene_name: str, scene_item_id: int) -> None:
        self.scenes[scene_name] = [
            item for item in self.scenes[scene_name] if int(item["sceneItemId"]) != scene_item_id
        ]
        self.transforms.pop(scene_item_id, None)
        self._renumber(scene_name)

    def get_scene_item_transform(self, scene_name: str, scene_item_id: int) -> dict[str, Any]:
        return deepcopy(self.transforms[scene_item_id])

    def set_scene_item_transform(self, scene_name: str, scene_item_id: int, transform: dict[str, Any]) -> None:
        if "boundsHeight" in transform and float(transform["boundsHeight"]) < 1.0:
            raise StreamOpsError(
                "SetSceneItemTransform failed (402): The field value of `boundsHeight` is below the minimum of `1.000000`"
            )
        self.transforms[scene_item_id].update(transform)

    def set_scene_item_enabled(self, scene_name: str, scene_item_id: int, enabled: bool) -> None:
        for item in self.scenes[scene_name]:
            if int(item["sceneItemId"]) == scene_item_id:
                item["sceneItemEnabled"] = enabled

    def set_scene_item_index(self, scene_name: str, scene_item_id: int, index: int) -> None:
        items = self.scenes[scene_name]
        target = next(item for item in items if int(item["sceneItemId"]) == scene_item_id)
        items.remove(target)
        items.insert(max(0, min(index, len(items))), target)
        self._renumber(scene_name)

    def get_current_program_scene(self) -> str | None:
        return self.current_scene

    def set_current_program_scene(self, scene_name: str) -> None:
        self.current_scene = scene_name

    def save_source_screenshot(self, source_name: str, output_path: Path, *, width: int, height: int) -> None:
        self.saved_screenshots.append(output_path)
        output_path.write_bytes(b"fake png")

    def get_record_status(self) -> dict[str, Any]:
        return {"outputActive": self.recording}

    def get_stream_status(self) -> dict[str, Any]:
        return {"outputActive": self.streaming}

    def start_record(self) -> None:
        self.recording = True

    def stop_record(self) -> dict[str, Any]:
        self.recording = False
        output_path = self.recording_output_path or Path("C:/Users/huy/Videos/fake.mp4")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake video")
        return {"outputPath": str(output_path)}

    def _renumber(self, scene_name: str) -> None:
        for index, item in enumerate(self.scenes[scene_name]):
            item["sceneItemIndex"] = index
