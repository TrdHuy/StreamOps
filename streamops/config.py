"""Scene configuration loading and validation."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigError


DEFAULT_CONFIG_DIR = Path("config") / "scenes"


@dataclass(frozen=True)
class VideoConfig:
    base_width: int
    base_height: int
    output_width: int
    output_height: int
    fps: int


@dataclass(frozen=True)
class SourceConfig:
    key: str
    source_name: str
    role: str
    layer: int
    fit: str | None = None
    anchor: str | None = None
    width_percent: float | None = None
    margin_right: float = 0
    margin_bottom: float = 0


@dataclass(frozen=True)
class SceneConfig:
    name: str
    video: VideoConfig
    sources: tuple[SourceConfig, ...]

    @property
    def main(self) -> SourceConfig:
        return self.source_by_role("main")

    @property
    def camera(self) -> SourceConfig:
        return self.source_by_role("camera")

    def source_by_role(self, role: str) -> SourceConfig:
        for source in self.sources:
            if source.role == role:
                return source
        raise ConfigError(f"Scene {self.name!r} is missing a {role!r} source.")


def find_project_root(start: Path | None = None) -> Path:
    """Find the repo root used for config and artifacts."""

    env_root = os.environ.get("STREAMOPS_HOME")
    if env_root:
        root = Path(env_root).expanduser().resolve()
        if not (root / DEFAULT_CONFIG_DIR).exists():
            raise ConfigError(f"STREAMOPS_HOME does not contain {DEFAULT_CONFIG_DIR}: {root}")
        return root

    candidates: list[Path] = []
    current = (start or Path.cwd()).resolve()
    candidates.extend([current, *current.parents])

    package_root = Path(__file__).resolve().parents[1]
    candidates.extend([package_root, *package_root.parents])

    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if (candidate / DEFAULT_CONFIG_DIR).exists():
            return candidate

    raise ConfigError(
        f"Could not find {DEFAULT_CONFIG_DIR}. Run from the repo root or set STREAMOPS_HOME."
    )


def load_scene_config(
    scene_name: str,
    *,
    root: Path | None = None,
    config_path: Path | None = None,
) -> SceneConfig:
    path = config_path or ((root or find_project_root()) / DEFAULT_CONFIG_DIR / f"{scene_name}.yaml")
    if not path.exists():
        raise ConfigError(f"Scene config not found: {path}")

    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    return parse_scene_config(raw, expected_name=scene_name, source=str(path))


def parse_scene_config(raw: dict[str, Any], *, expected_name: str, source: str = "<memory>") -> SceneConfig:
    if not isinstance(raw, dict):
        raise ConfigError(f"{source}: scene config must be a mapping.")

    name = _require_str(raw, "name", source)
    if name != expected_name:
        raise ConfigError(f"{source}: config name {name!r} does not match requested scene {expected_name!r}.")

    video_raw = _require_mapping(raw, "video", source)
    video = VideoConfig(
        base_width=_require_positive_int(video_raw, "base_width", source),
        base_height=_require_positive_int(video_raw, "base_height", source),
        output_width=_require_positive_int(video_raw, "output_width", source),
        output_height=_require_positive_int(video_raw, "output_height", source),
        fps=_require_positive_int(video_raw, "fps", source),
    )

    sources_raw = _require_mapping(raw, "sources", source)
    sources: list[SourceConfig] = []
    for key, value in sources_raw.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            raise ConfigError(f"{source}: every source entry must be a mapping.")
        sources.append(
            SourceConfig(
                key=key,
                source_name=_require_str(value, "source_name", source),
                role=_require_str(value, "role", source),
                layer=_require_int(value, "layer", source),
                fit=_optional_str(value, "fit", source),
                anchor=_optional_str(value, "anchor", source),
                width_percent=_optional_number(value, "width_percent", source),
                margin_right=_optional_number(value, "margin_right", source) or 0,
                margin_bottom=_optional_number(value, "margin_bottom", source) or 0,
            )
        )

    roles = {source.role for source in sources}
    missing_roles = {"main", "camera"} - roles
    if missing_roles:
        raise ConfigError(f"{source}: missing required source roles: {', '.join(sorted(missing_roles))}.")
    if len(roles) != len(sources):
        raise ConfigError(f"{source}: source roles must be unique.")

    source_names = {item.source_name for item in sources}
    if len(source_names) != len(sources):
        raise ConfigError(f"{source}: source_name values must be unique.")

    return SceneConfig(name=name, video=video, sources=tuple(sorted(sources, key=lambda item: item.layer)))


def _require_mapping(raw: dict[str, Any], key: str, source: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"{source}: {key!r} must be a mapping.")
    return value


def _require_str(raw: dict[str, Any], key: str, source: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{source}: {key!r} must be a non-empty string.")
    return value


def _optional_str(raw: dict[str, Any], key: str, source: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{source}: {key!r} must be a non-empty string when set.")
    return value


def _require_int(raw: dict[str, Any], key: str, source: str) -> int:
    value = raw.get(key)
    if not isinstance(value, int):
        raise ConfigError(f"{source}: {key!r} must be an integer.")
    return value


def _require_positive_int(raw: dict[str, Any], key: str, source: str) -> int:
    value = _require_int(raw, key, source)
    if value <= 0:
        raise ConfigError(f"{source}: {key!r} must be positive.")
    return value


def _optional_number(raw: dict[str, Any], key: str, source: str) -> float | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, int | float):
        raise ConfigError(f"{source}: {key!r} must be numeric when set.")
    return float(value)
