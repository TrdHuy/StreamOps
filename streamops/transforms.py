"""OBS scene-item transform calculations and comparison helpers."""

from __future__ import annotations

from typing import Any

from .config import SceneConfig, SourceConfig
from .errors import ConfigError, VerificationError


OBS_ALIGN_TOP_LEFT = 5
OBS_ALIGN_BOTTOM_RIGHT = 10
TRANSFORM_TOLERANCE = 0.01


def desired_transform(config: SceneConfig, source: SourceConfig, current_transform: dict[str, Any]) -> dict[str, Any]:
    if source.role == "main":
        return _main_transform(config)
    if source.role == "camera":
        return _camera_transform(config, source, current_transform)
    raise ConfigError(f"Unsupported source role: {source.role!r}")


def _main_transform(config: SceneConfig) -> dict[str, Any]:
    return {
        "alignment": OBS_ALIGN_TOP_LEFT,
        "positionX": 0.0,
        "positionY": 0.0,
        "rotation": 0.0,
        "cropLeft": 0,
        "cropRight": 0,
        "cropTop": 0,
        "cropBottom": 0,
        "boundsType": "OBS_BOUNDS_STRETCH",
        "boundsAlignment": OBS_ALIGN_TOP_LEFT,
        "boundsWidth": float(config.video.base_width),
        "boundsHeight": float(config.video.base_height),
    }


def _camera_transform(
    config: SceneConfig,
    source: SourceConfig,
    current_transform: dict[str, Any],
) -> dict[str, Any]:
    if source.anchor != "bottom_right":
        raise ConfigError(f"Unsupported camera anchor for {source.source_name!r}: {source.anchor!r}")
    if source.width_percent is None or source.width_percent <= 0:
        raise ConfigError(f"Camera source {source.source_name!r} requires a positive width_percent.")

    source_width = _positive_number(current_transform, "sourceWidth", source.source_name)
    target_width = config.video.base_width * (source.width_percent / 100.0)
    scale = target_width / source_width

    return {
        "alignment": OBS_ALIGN_BOTTOM_RIGHT,
        "positionX": float(config.video.base_width - source.margin_right),
        "positionY": float(config.video.base_height - source.margin_bottom),
        "scaleX": scale,
        "scaleY": scale,
        "rotation": 0.0,
        "cropLeft": 0,
        "cropRight": 0,
        "cropTop": 0,
        "cropBottom": 0,
        "boundsType": "OBS_BOUNDS_NONE",
        "boundsAlignment": OBS_ALIGN_TOP_LEFT,
        "boundsWidth": 0.0,
        "boundsHeight": 0.0,
    }


def transform_matches(actual: dict[str, Any], expected: dict[str, Any], *, tolerance: float = TRANSFORM_TOLERANCE) -> bool:
    return not transform_differences(actual, expected, tolerance=tolerance)


def transform_differences(
    actual: dict[str, Any],
    expected: dict[str, Any],
    *,
    tolerance: float = TRANSFORM_TOLERANCE,
) -> dict[str, dict[str, Any]]:
    differences: dict[str, dict[str, Any]] = {}
    for key, expected_value in expected.items():
        actual_value = actual.get(key)
        if isinstance(expected_value, int | float):
            if actual_value is None or abs(float(actual_value) - float(expected_value)) > tolerance:
                differences[key] = {"expected": expected_value, "actual": actual_value}
        elif actual_value != expected_value:
            differences[key] = {"expected": expected_value, "actual": actual_value}
    return differences


def _positive_number(raw: dict[str, Any], key: str, source_name: str) -> float:
    value = raw.get(key)
    if not isinstance(value, int | float) or value <= 0:
        raise VerificationError(
            f"OBS did not report a usable {key} for {source_name!r}; make sure the source is active."
        )
    return float(value)
