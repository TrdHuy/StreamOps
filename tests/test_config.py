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
                "main": {"source_name": "SRC-D4", "role": "main", "layer": 0, "fit": "stretch"},
                "camera": {
                    "source_name": "OpenStream V8",
                    "role": "camera",
                    "layer": 1,
                    "anchor": "bottom_right",
                    "width_percent": 22,
                    "margin_right": 80,
                    "margin_bottom": 80,
                },
            },
        },
        expected_name="gaming-poc",
    )

    assert config.name == "gaming-poc"
    assert config.video.base_width == 3840
    assert config.main.source_name == "SRC-D4"
    assert config.camera.source_name == "OpenStream V8"
