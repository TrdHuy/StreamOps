"""Review artifact generation for managed scenes."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import shutil
import time
from typing import Any, Protocol

from ..config import DEFAULT_ARTIFACT_DIR, find_project_root, load_scene_config
from ..errors import StreamOpsError
from ..obs.client import ObsClient
from ..obs.scene import Check, VerifyResult, verify_scene


class ReviewClient(Protocol):
    def close(self) -> None: ...
    def get_current_program_scene(self) -> str | None: ...
    def set_current_program_scene(self, scene_name: str) -> None: ...
    def save_source_screenshot(self, source_name: str, output_path: Path, *, width: int, height: int) -> None: ...
    def get_record_status(self) -> dict[str, Any]: ...
    def get_stream_status(self) -> dict[str, Any]: ...
    def start_record(self) -> None: ...
    def stop_record(self) -> dict[str, Any]: ...


def review_scene(
    scene_name: str,
    *,
    client: ReviewClient | None = None,
    root: Path | None = None,
    config_path: Path | None = None,
    artifact_root: Path | None = None,
    video_seconds: int | None = None,
) -> VerifyResult:
    project_root = root or find_project_root()
    config = load_scene_config(scene_name, root=project_root, config_path=config_path)
    artifact_dir = _artifact_dir(project_root, scene_name, artifact_root)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    owns_client = client is None
    obs = client or ObsClient.from_env()
    try:
        result = verify_scene(scene_name, client=obs, root=project_root, config_path=config_path)
        verify_path = artifact_dir / "verify.json"
        report_path = artifact_dir / "report.md"
        preview_path = artifact_dir / "preview.png"

        if result.status == "PASS":
            try:
                obs.save_source_screenshot(
                    scene_name,
                    preview_path,
                    width=config.video.output_width,
                    height=config.video.output_height,
                )
                result.artifacts["preview"] = str(preview_path)
            except StreamOpsError as exc:
                result.add(Check("artifact.preview", "FAIL", str(exc), expected="preview.png", actual=None))

            if video_seconds is not None and result.finalize().status == "PASS":
                try:
                    result.artifacts.update(_record_sample(obs, scene_name, video_seconds, artifact_dir))
                except StreamOpsError as exc:
                    result.add(Check("artifact.video", "FAIL", str(exc), expected=f"{video_seconds}s sample", actual=None))

        result.artifacts["verify"] = str(verify_path)
        result.artifacts["report"] = str(report_path)
        result.finalize()
        verify_path.write_text(json.dumps(result.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        report_path.write_text(_render_report(result), encoding="utf-8")
        return result
    finally:
        if owns_client:
            obs.close()


def _artifact_dir(project_root: Path, scene_name: str, artifact_root: Path | None) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    root = artifact_root or (project_root / DEFAULT_ARTIFACT_DIR)
    return (root / scene_name / timestamp).resolve()


def _record_sample(obs: ReviewClient, scene_name: str, seconds: int, artifact_dir: Path) -> dict[str, str]:
    if seconds <= 0 or seconds > 300:
        raise StreamOpsError("--video must be between 1 and 300 seconds.")

    stream_status = obs.get_stream_status()
    record_status = obs.get_record_status()
    if stream_status.get("outputActive"):
        raise StreamOpsError("Refusing video review while streaming is active.")
    if record_status.get("outputActive"):
        raise StreamOpsError("Refusing video review while recording is already active.")

    previous_scene = obs.get_current_program_scene()
    started_recording = False
    try:
        obs.set_current_program_scene(scene_name)
        obs.start_record()
        started_recording = True
        time.sleep(seconds)
        stop_response = obs.stop_record()
        started_recording = False
        output_path = stop_response.get("outputPath")
        if not output_path:
            raise StreamOpsError("OBS stopped recording but did not return an outputPath.")
        source_path = Path(output_path).expanduser()
        _wait_for_stable_file(source_path)

        target_path = artifact_dir / _sample_video_name(seconds, source_path)
        try:
            shutil.copy2(source_path, target_path)
        except OSError as exc:
            raise StreamOpsError(f"Could not copy video sample into review artifacts: {exc}") from exc
        _wait_for_stable_file(target_path, timeout_seconds=5, poll_seconds=0.2)
        return {"video": str(target_path), "video_source": str(source_path)}
    finally:
        stop_error: StreamOpsError | None = None
        if started_recording:
            try:
                obs.stop_record()
            except StreamOpsError as exc:
                stop_error = exc
        if previous_scene and previous_scene != scene_name:
            obs.set_current_program_scene(previous_scene)
        if stop_error:
            raise stop_error


def _wait_for_stable_file(path: Path, *, timeout_seconds: float = 30, poll_seconds: float = 0.5) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_size: int | None = None
    stable_observations = 0
    last_error: OSError | None = None

    while time.monotonic() < deadline:
        try:
            size = path.stat().st_size
            last_error = None
        except OSError as exc:
            size = 0
            last_error = exc

        if size > 0 and size == last_size:
            stable_observations += 1
        elif size > 0:
            stable_observations = 1
        else:
            stable_observations = 0

        if stable_observations >= 2:
            return

        last_size = size
        time.sleep(poll_seconds)

    if last_error:
        raise StreamOpsError(f"Video sample was not readable after recording: {path} ({last_error})")
    raise StreamOpsError(f"Video sample was not finalized or remained empty after recording: {path}")


def _sample_video_name(seconds: int, source_path: Path) -> str:
    suffix = source_path.suffix or ".mp4"
    return f"sample-{seconds}s{suffix}"


def _render_report(result: VerifyResult) -> str:
    lines = [
        f"# {result.scene} Review: {result.status}",
        "",
        f"- Generated: `{result.generated_at}`",
        f"- OBS version: `{result.obs_version or 'unknown'}`",
        "",
        "## Checks",
        "",
    ]
    for check in result.checks:
        lines.append(f"- `{check.status}` `{check.id}`: {check.message}")

    lines.extend(["", "## Artifacts", ""])
    for name, path in sorted(result.artifacts.items()):
        lines.append(f"- `{name}`: `{path}`")
    return "\n".join(lines) + "\n"
