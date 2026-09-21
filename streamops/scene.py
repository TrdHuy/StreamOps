"""Idempotent OBS scene reconciliation and verification."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from .config import SceneConfig, load_scene_config
from .errors import StreamOpsError
from .obs_client import ObsClient
from .transforms import desired_transform, transform_differences, transform_matches


class SceneClient(Protocol):
    def close(self) -> None: ...
    def get_version(self) -> dict[str, Any]: ...
    def get_video_settings(self) -> dict[str, Any]: ...
    def set_video_settings(self, settings: dict[str, Any]) -> None: ...
    def get_record_status(self) -> dict[str, Any]: ...
    def get_stream_status(self) -> dict[str, Any]: ...
    def get_scene_list(self) -> list[dict[str, Any]]: ...
    def create_scene(self, scene_name: str) -> None: ...
    def get_input_list(self) -> list[dict[str, Any]]: ...
    def get_scene_item_list(self, scene_name: str) -> list[dict[str, Any]]: ...
    def create_scene_item(self, scene_name: str, source_name: str, *, enabled: bool = True) -> int: ...
    def remove_scene_item(self, scene_name: str, scene_item_id: int) -> None: ...
    def get_scene_item_transform(self, scene_name: str, scene_item_id: int) -> dict[str, Any]: ...
    def set_scene_item_transform(self, scene_name: str, scene_item_id: int, transform: dict[str, Any]) -> None: ...
    def set_scene_item_enabled(self, scene_name: str, scene_item_id: int, enabled: bool) -> None: ...
    def set_scene_item_index(self, scene_name: str, scene_item_id: int, index: int) -> None: ...


@dataclass(frozen=True)
class Change:
    action: str
    detail: str


@dataclass(frozen=True)
class ApplyResult:
    scene: str
    changed: bool
    changes: tuple[Change, ...]


@dataclass(frozen=True)
class Check:
    id: str
    status: str
    message: str
    expected: Any = None
    actual: Any = None


@dataclass
class VerifyResult:
    scene: str
    status: str
    generated_at: str
    obs_version: str | None
    checks: list[Check] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)

    def add(self, check: Check) -> None:
        self.checks.append(check)

    def finalize(self) -> "VerifyResult":
        self.status = "FAIL" if any(check.status == "FAIL" for check in self.checks) else "PASS"
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene": self.scene,
            "status": self.status,
            "generated_at": self.generated_at,
            "obs_version": self.obs_version,
            "checks": [
                {
                    "id": check.id,
                    "status": check.status,
                    "message": check.message,
                    "expected": check.expected,
                    "actual": check.actual,
                }
                for check in self.checks
            ],
            "artifacts": self.artifacts,
        }


def apply_scene(
    scene_name: str,
    *,
    client: SceneClient | None = None,
    root: Path | None = None,
    config_path: Path | None = None,
) -> ApplyResult:
    config = load_scene_config(scene_name, root=root, config_path=config_path)
    owns_client = client is None
    obs: SceneClient = client or ObsClient.from_env()

    changes: list[Change] = []
    try:
        obs.get_version()
        _ensure_video_settings(obs, config, changes)
        _ensure_configured_sources_exist(obs, config)
        _ensure_scene_exists(obs, config, changes)
        _remove_duplicate_configured_items(obs, config, changes)
        item_ids = _ensure_configured_scene_items(obs, config, changes)
        _apply_transforms(obs, config, item_ids, changes)
        _apply_visibility(obs, config, item_ids, changes)
        _apply_order(obs, config, item_ids, changes)
    finally:
        if owns_client:
            obs.close()

    return ApplyResult(scene=config.name, changed=bool(changes), changes=tuple(changes))


def verify_scene(
    scene_name: str,
    *,
    client: SceneClient | None = None,
    root: Path | None = None,
    config_path: Path | None = None,
) -> VerifyResult:
    config = load_scene_config(scene_name, root=root, config_path=config_path)
    owns_client = client is None
    obs: SceneClient = client or ObsClient.from_env()
    result = VerifyResult(
        scene=config.name,
        status="FAIL",
        generated_at=datetime.now(timezone.utc).isoformat(),
        obs_version=None,
    )

    try:
        version = obs.get_version()
        result.obs_version = version.get("obsVersion") or version.get("obsStudioVersion")
        _verify_video(obs, config, result)
        _verify_sources(obs, config, result)
        scene_exists = _scene_exists(obs, config.name)
        result.add(
            Check(
                id="scene.exists",
                status="PASS" if scene_exists else "FAIL",
                message=f"Scene {config.name!r} exists." if scene_exists else f"Scene {config.name!r} is missing.",
                expected=True,
                actual=scene_exists,
            )
        )
        if scene_exists:
            _verify_items(obs, config, result)
    finally:
        if owns_client:
            obs.close()

    return result.finalize()


def _ensure_video_settings(obs: SceneClient, config: SceneConfig, changes: list[Change]) -> None:
    current = obs.get_video_settings()
    desired = _video_request(config)
    if _video_matches(current, config):
        return
    if obs.get_stream_status().get("outputActive") or obs.get_record_status().get("outputActive"):
        raise StreamOpsError(
            "OBS video settings differ from the scene config, but streaming or recording is active. "
            "Stop active outputs before applying video settings."
        )
    obs.set_video_settings(desired)
    changes.append(Change("video.set", f"Set OBS video to {config.video.base_width}x{config.video.base_height}@{config.video.fps}."))


def _ensure_configured_sources_exist(obs: SceneClient, config: SceneConfig) -> None:
    inputs = {item.get("inputName") for item in obs.get_input_list()}
    scenes = {item.get("sceneName") for item in obs.get_scene_list()}
    available_sources = inputs | scenes
    missing = [source.source_name for source in config.sources if source.source_name not in available_sources]
    if missing:
        raise StreamOpsError(
            "Configured OBS source(s) are missing: "
            + ", ".join(repr(item) for item in missing)
            + ". Create or rename the sources in OBS, or update the scene config."
        )


def _ensure_scene_exists(obs: SceneClient, config: SceneConfig, changes: list[Change]) -> None:
    if _scene_exists(obs, config.name):
        return
    obs.create_scene(config.name)
    changes.append(Change("scene.create", f"Created scene {config.name!r}."))


def _remove_duplicate_configured_items(obs: SceneClient, config: SceneConfig, changes: list[Change]) -> None:
    items = obs.get_scene_item_list(config.name)
    for source in config.sources:
        matching = [item for item in items if item.get("sourceName") == source.source_name]
        if len(matching) <= 1:
            continue
        keep = min(matching, key=lambda item: int(item["sceneItemId"]))
        for item in matching:
            if item is keep:
                continue
            obs.remove_scene_item(config.name, int(item["sceneItemId"]))
            changes.append(Change("item.remove_duplicate", f"Removed duplicate scene item for {source.source_name!r}."))


def _ensure_configured_scene_items(
    obs: SceneClient,
    config: SceneConfig,
    changes: list[Change],
) -> dict[str, int]:
    item_ids: dict[str, int] = {}
    items = obs.get_scene_item_list(config.name)
    for source in config.sources:
        item = _find_scene_item(items, source.source_name)
        if item is None:
            scene_item_id = obs.create_scene_item(config.name, source.source_name, enabled=True)
            changes.append(Change("item.create", f"Added {source.source_name!r} to {config.name!r}."))
        else:
            scene_item_id = int(item["sceneItemId"])
        item_ids[source.role] = scene_item_id
    return item_ids


def _apply_transforms(
    obs: SceneClient,
    config: SceneConfig,
    item_ids: dict[str, int],
    changes: list[Change],
) -> None:
    for source in config.sources:
        scene_item_id = item_ids[source.role]
        current = obs.get_scene_item_transform(config.name, scene_item_id)
        desired = desired_transform(config, source, current)
        if transform_matches(current, desired):
            continue
        obs.set_scene_item_transform(config.name, scene_item_id, desired)
        changes.append(Change("item.transform", f"Updated transform for {source.source_name!r}."))


def _apply_visibility(
    obs: SceneClient,
    config: SceneConfig,
    item_ids: dict[str, int],
    changes: list[Change],
) -> None:
    items = obs.get_scene_item_list(config.name)
    enabled_by_id = {int(item["sceneItemId"]): bool(item.get("sceneItemEnabled", True)) for item in items}
    for source in config.sources:
        scene_item_id = item_ids[source.role]
        if enabled_by_id.get(scene_item_id) is True:
            continue
        obs.set_scene_item_enabled(config.name, scene_item_id, True)
        changes.append(Change("item.enable", f"Enabled scene item for {source.source_name!r}."))


def _apply_order(
    obs: SceneClient,
    config: SceneConfig,
    item_ids: dict[str, int],
    changes: list[Change],
) -> None:
    main_id = item_ids[config.main.role]
    camera_id = item_ids[config.camera.role]
    items = obs.get_scene_item_list(config.name)
    current = {int(item["sceneItemId"]): int(item.get("sceneItemIndex", 0)) for item in items}

    if current.get(main_id) != 0:
        obs.set_scene_item_index(config.name, main_id, 0)
        changes.append(Change("item.order", f"Moved {config.main.source_name!r} to the bottom layer."))

    items_after_main = obs.get_scene_item_list(config.name)
    max_index = max(0, len(items_after_main) - 1)
    current_after_main = {int(item["sceneItemId"]): int(item.get("sceneItemIndex", 0)) for item in items_after_main}
    if current_after_main.get(camera_id) != max_index:
        obs.set_scene_item_index(config.name, camera_id, max_index)
        changes.append(Change("item.order", f"Moved {config.camera.source_name!r} above the main source."))


def _verify_video(obs: SceneClient, config: SceneConfig, result: VerifyResult) -> None:
    current = obs.get_video_settings()
    expected = _video_request(config)
    result.add(
        Check(
            id="video.settings",
            status="PASS" if _video_matches(current, config) else "FAIL",
            message="OBS video settings match the scene requirement.",
            expected=expected,
            actual={key: current.get(key) for key in expected},
        )
    )


def _verify_sources(obs: SceneClient, config: SceneConfig, result: VerifyResult) -> None:
    inputs = {item.get("inputName") for item in obs.get_input_list()}
    scenes = {item.get("sceneName") for item in obs.get_scene_list()}
    available_sources = inputs | scenes
    for source in config.sources:
        exists = source.source_name in available_sources
        result.add(
            Check(
                id=f"source.{source.role}.exists",
                status="PASS" if exists else "FAIL",
                message=f"Source {source.source_name!r} exists." if exists else f"Source {source.source_name!r} is missing.",
                expected=True,
                actual=exists,
            )
        )


def _verify_items(obs: SceneClient, config: SceneConfig, result: VerifyResult) -> None:
    items = obs.get_scene_item_list(config.name)
    configured_names = {source.source_name for source in config.sources}
    unknown_visible = [
        item.get("sourceName")
        for item in items
        if item.get("sourceName") not in configured_names and bool(item.get("sceneItemEnabled", True))
    ]
    if unknown_visible:
        result.add(
            Check(
                id="scene.unmanaged_visible_items",
                status="WARN",
                message="Scene has visible unmanaged item(s); StreamOps preserved them.",
                expected=[],
                actual=unknown_visible,
            )
        )

    indexes: dict[str, int] = {}
    for source in config.sources:
        matching = [item for item in items if item.get("sourceName") == source.source_name]
        result.add(
            Check(
                id=f"item.{source.role}.count",
                status="PASS" if len(matching) == 1 else "FAIL",
                message=f"Scene has exactly one item for {source.source_name!r}.",
                expected=1,
                actual=len(matching),
            )
        )
        if len(matching) != 1:
            continue

        item = matching[0]
        scene_item_id = int(item["sceneItemId"])
        indexes[source.role] = int(item.get("sceneItemIndex", 0))
        enabled = bool(item.get("sceneItemEnabled", True))
        result.add(
            Check(
                id=f"item.{source.role}.enabled",
                status="PASS" if enabled else "FAIL",
                message=f"{source.source_name!r} is visible.",
                expected=True,
                actual=enabled,
            )
        )

        current_transform = obs.get_scene_item_transform(config.name, scene_item_id)
        expected_transform = desired_transform(config, source, current_transform)
        differences = transform_differences(current_transform, expected_transform)
        result.add(
            Check(
                id=f"item.{source.role}.transform",
                status="PASS" if not differences else "FAIL",
                message=f"{source.source_name!r} transform matches desired layout.",
                expected=expected_transform,
                actual=differences or {key: current_transform.get(key) for key in expected_transform},
            )
        )

    if "main" in indexes and "camera" in indexes:
        ordered = indexes["main"] < indexes["camera"]
        result.add(
            Check(
                id="item.order",
                status="PASS" if ordered else "FAIL",
                message="Camera item is above the main source.",
                expected="main index < camera index",
                actual={"main": indexes["main"], "camera": indexes["camera"]},
            )
        )


def _scene_exists(obs: SceneClient, scene_name: str) -> bool:
    return any(item.get("sceneName") == scene_name for item in obs.get_scene_list())


def _find_scene_item(items: list[dict[str, Any]], source_name: str) -> dict[str, Any] | None:
    for item in items:
        if item.get("sourceName") == source_name:
            return item
    return None


def _video_request(config: SceneConfig) -> dict[str, Any]:
    return {
        "baseWidth": config.video.base_width,
        "baseHeight": config.video.base_height,
        "outputWidth": config.video.output_width,
        "outputHeight": config.video.output_height,
        "fpsNumerator": config.video.fps,
        "fpsDenominator": 1,
    }


def _video_matches(current: dict[str, Any], config: SceneConfig) -> bool:
    expected = _video_request(config)
    return all(int(current.get(key, -1)) == int(value) for key, value in expected.items())
