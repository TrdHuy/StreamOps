import pytest

from streamops.errors import ConfigError
from streamops.config import parse_scene_config


def test_parse_gaming_poc_config() -> None:
    config = parse_scene_config(
        {
            "name": "gaming-poc",
            "video": {
                "base_width": 3840,
                "base_height": 2160,
                "output_width": 3840,
                "output_height": 2160,
                "fps": 30,
            },
            "sources": {
                "main": {
                    "source_name": "StreamOps Desktop POC",
                    "role": "main",
                    "layer": 0,
                    "fit": "stretch",
                    "managed": True,
                    "input_kind": "monitor_capture",
                    "settings": {},
                },
                "overlay": {
                    "source_name": "StreamOps Clock POC",
                    "role": "overlay",
                    "layer": 1,
                    "anchor": "bottom_right",
                    "width_percent": 22,
                    "margin_right": 80,
                    "margin_bottom": 80,
                    "managed": True,
                    "input_kind": "browser_source",
                    "settings": {
                        "is_local_file": True,
                        "local_file": "obs/assets/clock-overlay.html",
                        "width": 844,
                        "height": 475,
                    },
                },
            },
        },
        expected_name="gaming-poc",
    )

    assert config.name == "gaming-poc"
    assert config.video.base_width == 3840
    assert config.main.source_name == "StreamOps Desktop POC"
    assert config.overlay.source_name == "StreamOps Clock POC"
    assert config.overlay.managed is True
    assert config.overlay.input_kind == "browser_source"
    assert config.overlay.settings["local_file"] == "obs/assets/clock-overlay.html"


def test_managed_source_requires_input_kind() -> None:
    with pytest.raises(ConfigError, match="requires 'input_kind'"):
        parse_scene_config(
            {
                "name": "gaming-poc",
                "video": {
                    "base_width": 3840,
                    "base_height": 2160,
                    "output_width": 3840,
                    "output_height": 2160,
                    "fps": 30,
                },
                "sources": {
                    "main": {"source_name": "StreamOps Desktop POC", "role": "main", "layer": 0},
                    "overlay": {
                        "source_name": "StreamOps Clock POC",
                        "role": "overlay",
                        "layer": 1,
                        "managed": True,
                    },
                },
            },
            expected_name="gaming-poc",
        )
