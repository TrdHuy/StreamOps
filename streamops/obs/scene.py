"""Idempotent OBS scene reconciliation and verification."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
from pathlib import Path
import re
from typing import Any, Protocol

from ..config import SceneConfig, SourceConfig, find_project_root, load_scene_config
from ..errors import ConfigError, StreamOpsError
from .client import ObsClient
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
    def get_input_kind_list(self) -> list[str]: ...
    def create_input(
        self,
        scene_name: str,
        input_name: str,
        input_kind: str,
        input_settings: dict[str, Any],
        *,
        enabled: bool = True,
    ) -> int: ...
    def get_input_settings(self, input_name: str) -> dict[str, Any]: ...
    def get_input_properties_list_property_items(self, input_name: str, property_name: str) -> list[dict[str, Any]]: ...
    def get_monitor_list(self) -> list[dict[str, Any]]: ...
    def set_input_settings(self, input_name: str, settings: dict[str, Any], *, overlay: bool = True) -> None: ...
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
    project_root = root or find_project_root()
    config = load_scene_config(scene_name, root=project_root, config_path=config_path)
    owns_client = client is None
    obs: SceneClient = client or ObsClient.from_env()

    changes: list[Change] = []
    try:
        obs.get_version()
        _preflight_configured_sources(obs, config, project_root)
        _ensure_video_settings(obs, config, changes)
        _ensure_scene_exists(obs, config, changes)
        _ensure_managed_inputs(obs, config, project_root, changes)
        _remove_duplicate_configured_items(obs, config, changes)
        item_ids = _ensure_configured_scene_items(obs, config, changes)
        _disable_unmanaged_items(obs, config, changes)
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
    project_root = root or find_project_root()
    config = load_scene_config(scene_name, root=project_root, config_path=config_path)
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
        _verify_sources(obs, config, result, project_root)
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


def _preflight_configured_sources(obs: SceneClient, config: SceneConfig, root: Path) -> None:
    inputs = _inputs_by_name(obs)
    scenes = {item.get("sceneName") for item in obs.get_scene_list()}
    available_sources = set(inputs) | scenes

    missing_external = [
        source.source_name
        for source in config.sources
        if not source.managed and source.source_name not in available_sources
    ]
    if missing_external:
        raise StreamOpsError(
            "Configured OBS source(s) are missing: "
            + ", ".join(repr(item) for item in missing_external)
            + ". Create or rename the sources in OBS, or update the scene config."
        )

    managed_sources = [source for source in config.sources if source.managed]
    if not managed_sources:
        return

    input_kinds = set(obs.get_input_kind_list())
    unsupported = sorted(
        {
            source.input_kind
            for source in managed_sources
            if source.input_kind is not None and source.input_kind not in input_kinds
        }
    )
    if unsupported:
        raise StreamOpsError(
            "OBS does not support required input kind(s): "
            + ", ".join(repr(item) for item in unsupported)
            + ". Install/enable the required OBS source plugins before applying."
        )

    for source in managed_sources:
        _resolve_input_settings(obs, source, root, inputs)
        if source.source_name in scenes:
            raise StreamOpsError(
                f"Managed source {source.source_name!r} conflicts with an existing OBS scene name."
            )

        existing = inputs.get(source.source_name)
        if existing is None:
            continue
        actual_kinds = {
            kind
            for kind in (existing.get("inputKind"), existing.get("unversionedInputKind"))
            if isinstance(kind, str)
        }
        if actual_kinds and source.input_kind not in actual_kinds:
            raise StreamOpsError(
                f"Managed source {source.source_name!r} already exists with input kind "
                f"{sorted(actual_kinds)!r}, expected {source.input_kind!r}. Rename the existing source or update the config."
            )


def _ensure_managed_inputs(
    obs: SceneClient,
    config: SceneConfig,
    root: Path,
    changes: list[Change],
) -> None:
    inputs = _inputs_by_name(obs)
    for source in config.sources:
        if not source.managed:
            continue

        desired_settings = _resolve_input_settings(obs, source, root, inputs)
        if source.source_name not in inputs:
            if source.input_kind is None:
                raise ConfigError(f"Managed source {source.source_name!r} requires an input_kind.")
            obs.create_input(
                config.name,
                source.source_name,
                source.input_kind,
                desired_settings,
                enabled=True,
            )
            changes.append(
                Change("input.create", f"Created managed {source.input_kind!r} input {source.source_name!r}.")
            )
            inputs[source.source_name] = {"inputName": source.source_name, "inputKind": source.input_kind}
            continue

        current_settings = obs.get_input_settings(source.source_name)
        if _settings_match(current_settings, desired_settings):
            continue
        obs.set_input_settings(source.source_name, desired_settings, overlay=True)
        changes.append(Change("input.settings", f"Updated settings for managed input {source.source_name!r}."))


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


def _disable_unmanaged_items(obs: SceneClient, config: SceneConfig, changes: list[Change]) -> None:
    configured_names = {source.source_name for source in config.sources}
    for item in obs.get_scene_item_list(config.name):
        if item.get("sourceName") in configured_names or not bool(item.get("sceneItemEnabled", True)):
            continue
        scene_item_id = int(item["sceneItemId"])
        obs.set_scene_item_enabled(config.name, scene_item_id, False)
        changes.append(Change("item.disable_unmanaged", f"Disabled unmanaged item {item.get('sourceName')!r}."))


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
    overlay = config.overlay
    overlay_id = item_ids[overlay.role]
    items = obs.get_scene_item_list(config.name)
    current = {int(item["sceneItemId"]): int(item.get("sceneItemIndex", 0)) for item in items}

    if current.get(main_id) != 0:
        obs.set_scene_item_index(config.name, main_id, 0)
        changes.append(Change("item.order", f"Moved {config.main.source_name!r} to the bottom layer."))

    items_after_main = obs.get_scene_item_list(config.name)
    max_index = max(0, len(items_after_main) - 1)
    current_after_main = {int(item["sceneItemId"]): int(item.get("sceneItemIndex", 0)) for item in items_after_main}
    if current_after_main.get(overlay_id) != max_index:
        obs.set_scene_item_index(config.name, overlay_id, max_index)
        changes.append(Change("item.order", f"Moved {overlay.source_name!r} above the main source."))


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


def _verify_sources(obs: SceneClient, config: SceneConfig, result: VerifyResult, root: Path) -> None:
    input_items = _inputs_by_name(obs)
    inputs = set(input_items)
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
        if not exists or not source.managed:
            continue

        input_item = input_items.get(source.source_name) or {}
        actual_kinds = {
            kind
            for kind in (input_item.get("inputKind"), input_item.get("unversionedInputKind"))
            if isinstance(kind, str)
        }
        kind_matches = not actual_kinds or source.input_kind in actual_kinds
        result.add(
            Check(
                id=f"source.{source.role}.kind",
                status="PASS" if kind_matches else "FAIL",
                message=f"{source.source_name!r} uses the expected managed input kind.",
                expected=source.input_kind,
                actual=sorted(actual_kinds) or None,
            )
        )

        expected_settings = _resolve_input_settings(obs, source, root, input_items)
        current_settings = obs.get_input_settings(source.source_name)
        settings_differences = _settings_differences(current_settings, expected_settings)
        result.add(
            Check(
                id=f"source.{source.role}.settings",
                status="PASS" if not settings_differences else "FAIL",
                message=f"{source.source_name!r} managed input settings match desired values.",
                expected=expected_settings,
                actual=settings_differences or {key: current_settings.get(key) for key in expected_settings},
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

    overlay_role = config.overlay.role
    if "main" in indexes and overlay_role in indexes:
        ordered = indexes["main"] < indexes[overlay_role]
        result.add(
            Check(
                id="item.order",
                status="PASS" if ordered else "FAIL",
                message="Overlay item is above the main source.",
                expected=f"main index < {overlay_role} index",
                actual={"main": indexes["main"], overlay_role: indexes[overlay_role]},
            )
        )


def _scene_exists(obs: SceneClient, scene_name: str) -> bool:
    return any(item.get("sceneName") == scene_name for item in obs.get_scene_list())


def _inputs_by_name(obs: SceneClient) -> dict[str, dict[str, Any]]:
    return {
        str(item["inputName"]): item
        for item in obs.get_input_list()
        if isinstance(item.get("inputName"), str)
    }


def _find_scene_item(items: list[dict[str, Any]], source_name: str) -> dict[str, Any] | None:
    for item in items:
        if item.get("sourceName") == source_name:
            return item
    return None


def _resolve_input_settings(
    obs: SceneClient,
    source: SourceConfig,
    root: Path,
    inputs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    settings = dict(source.settings)
    local_file = settings.get("local_file")
    if local_file is not None:
        if not isinstance(local_file, str) or not local_file.strip():
            raise ConfigError(f"Managed source {source.source_name!r} has invalid 'local_file' setting.")

        path = Path(local_file).expanduser()
        if not path.is_absolute():
            path = root / path
        path = path.resolve()
        if not path.exists():
            raise ConfigError(f"Managed source {source.source_name!r} local_file does not exist: {path}")
        settings["local_file"] = str(path)

    if source.input_kind == "monitor_capture":
        settings = _resolve_monitor_capture_settings(obs, source, settings, inputs)

    return settings


def _resolve_monitor_capture_settings(
    obs: SceneClient,
    source: SourceConfig,
    settings: dict[str, Any],
    inputs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    monitor_id = settings.get("monitor_id")
    if monitor_id == "auto":
        settings["monitor_id"] = _select_monitor_id(obs, source, inputs)
    elif not _valid_monitor_id(monitor_id):
        raise ConfigError(
            f"Managed monitor_capture source {source.source_name!r} requires a valid monitor_id or 'auto'."
        )
    return settings


def _select_monitor_id(obs: SceneClient, source: SourceConfig, inputs: dict[str, dict[str, Any]]) -> str:
    if source.source_name in inputs:
        try:
            monitor_id = _select_monitor_id_from_property_items(
                obs.get_input_properties_list_property_items(source.source_name, "monitor_id")
            )
            if monitor_id:
                return monitor_id
        except StreamOpsError:
            pass

    try:
        monitor_id = _select_monitor_id_from_monitor_list(obs.get_monitor_list())
        if monitor_id:
            return monitor_id
    except StreamOpsError:
        pass

    for monitor_id in _windows_monitor_ids():
        if _valid_monitor_id(monitor_id):
            return monitor_id

    raise StreamOpsError(
        f"Could not resolve a valid desktop display for {source.source_name!r}. "
        "OBS reported no enabled monitor_capture display."
    )


def _select_monitor_id_from_property_items(items: list[dict[str, Any]]) -> str | None:
    candidates = [
        item
        for item in items
        if item.get("itemEnabled", True) is True and _valid_monitor_id(item.get("itemValue"))
    ]
    if not candidates:
        return None
    primary = [
        item
        for item in candidates
        if "primary" in str(item.get("itemName", "")).casefold()
    ]
    selected = primary[0] if primary else candidates[0]
    return str(selected["itemValue"])


def _select_monitor_id_from_monitor_list(monitors: list[dict[str, Any]]) -> str | None:
    ordered = sorted(monitors, key=lambda item: int(item.get("monitorIndex", 9999)))
    for monitor in ordered:
        name = monitor.get("monitorName")
        if not isinstance(name, str):
            continue
        monitor_id = re.sub(r"\(\d+\)$", "", name)
        if _valid_monitor_id(monitor_id):
            return monitor_id
    return None


def _valid_monitor_id(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value != "DUMMY"


def _windows_monitor_ids() -> list[str]:
    if os.name != "nt":
        return []

    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return []

    user32 = ctypes.windll.user32
    cch_device_name = 32
    edd_get_device_interface_name = 0x00000001

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    class MONITORINFOEXA(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", RECT),
            ("rcWork", RECT),
            ("dwFlags", wintypes.DWORD),
            ("szDevice", ctypes.c_char * cch_device_name),
        ]

    class DISPLAY_DEVICEA(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("DeviceName", ctypes.c_char * 32),
            ("DeviceString", ctypes.c_char * 128),
            ("StateFlags", wintypes.DWORD),
            ("DeviceID", ctypes.c_char * 128),
            ("DeviceKey", ctypes.c_char * 128),
        ]

    monitor_enum_proc = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HMONITOR,
        wintypes.HDC,
        ctypes.POINTER(RECT),
        wintypes.LPARAM,
    )
    monitor_ids: list[str] = []

    def decode(raw: bytes) -> str:
        return raw.split(b"\x00", 1)[0].decode("mbcs", errors="replace")

    def callback(handle: Any, hdc: Any, rect: Any, param: Any) -> bool:
        info = MONITORINFOEXA()
        info.cbSize = ctypes.sizeof(info)
        if user32.GetMonitorInfoA(handle, ctypes.byref(info)):
            device = DISPLAY_DEVICEA()
            device.cb = ctypes.sizeof(device)
            if user32.EnumDisplayDevicesA(info.szDevice, 0, ctypes.byref(device), edd_get_device_interface_name):
                monitor_ids.append(decode(device.DeviceID))
            monitor_ids.append(decode(info.szDevice))
        return True

    user32.EnumDisplayMonitors(0, 0, monitor_enum_proc(callback), 0)
    return monitor_ids


def _settings_match(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    return not _settings_differences(actual, expected)


def _settings_differences(actual: dict[str, Any], expected: dict[str, Any]) -> dict[str, dict[str, Any]]:
    differences: dict[str, dict[str, Any]] = {}
    for key, expected_value in expected.items():
        actual_value = actual.get(key)
        if not _setting_values_match(key, actual_value, expected_value):
            differences[key] = {"expected": expected_value, "actual": actual_value}
    return differences


def _setting_values_match(key: str, actual: Any, expected: Any) -> bool:
    if key == "local_file" and isinstance(actual, str) and isinstance(expected, str):
        return _normalized_file_path(actual) == _normalized_file_path(expected)
    if isinstance(expected, bool):
        return bool(actual) is expected
    if isinstance(expected, int | float) and not isinstance(expected, bool):
        try:
            return abs(float(actual) - float(expected)) <= 0.01
        except (TypeError, ValueError):
            return False
    return actual == expected


def _normalized_file_path(value: str) -> str:
    try:
        return str(Path(value).expanduser().resolve(strict=False)).casefold()
    except OSError:
        return str(Path(value).expanduser()).casefold()


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
