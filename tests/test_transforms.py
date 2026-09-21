from streamops.config import SceneConfig, SourceConfig, VideoConfig
from streamops.transforms import desired_transform


def test_camera_transform_uses_bottom_right_anchor() -> None:
    config = SceneConfig(
        name="gaming-poc",
        video=VideoConfig(3840, 2160, 3840, 2160, 30),
        sources=(
            SourceConfig("main", "SRC-D4", "main", 0),
            SourceConfig(
                "camera",
                "OpenStream V8",
                "camera",
                1,
                anchor="bottom_right",
                width_percent=22,
                margin_right=80,
                margin_bottom=80,
            ),
        ),
    )

    transform = desired_transform(config, config.camera, {"sourceWidth": 1920, "sourceHeight": 1080})

    assert transform["positionX"] == 3760
    assert transform["positionY"] == 2080
    assert transform["scaleX"] == transform["scaleY"] == 0.44
    assert transform["alignment"] == 10
