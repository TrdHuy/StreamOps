# Issue #1 POC Handoff

## Implemented

- `streamops scene apply gaming-poc` reconciles the managed OBS scene from `config/scenes/gaming-poc.yaml`.
- `streamops scene review gaming-poc` verifies the scene and writes review artifacts under `artifacts/gaming-poc/<timestamp>/`.
- `streamops scene review gaming-poc --video 5` records an optional sample video when OBS is not already streaming or recording.
- The POC creates/reconciles StreamOps-owned OBS inputs for the current desktop and a browser clock overlay. It does not depend on Diablo IV, `SRC-D4`, `OpenStream V8`, or a live phone camera.

## Reviewer Commands

```powershell
python -m pip install -e ".[dev]"
$env:OBS_WEBSOCKET_HOST = "127.0.0.1"
$env:OBS_WEBSOCKET_PORT = "4455"
# Optional override. If omitted, StreamOps reads the local OBS WebSocket config.
$env:OBS_WEBSOCKET_PASSWORD = "<password-if-enabled>"

streamops scene apply gaming-poc
streamops scene apply gaming-poc
streamops scene review gaming-poc
streamops scene review gaming-poc --video 5
```

Local OBS E2E harness:

```powershell
# Optional when OBS WebSocket password is present in the local OBS config.
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/local/e2e-gaming-poc.ps1
```

## Artifacts

```text
artifacts/
└── gaming-poc/
    └── <timestamp>/
        ├── preview.png
        ├── verify.json
        └── report.md
```

When `--video` is used, OBS writes the video to its configured recording directory and the output path is recorded in `verify.json` and `report.md`.
StreamOps waits for that file to finalize, copies it into the same timestamped review artifact directory as `sample-<seconds>s.<ext>`, and records both the copied artifact path and original OBS output path.
Open the 5 second video artifact and confirm the bottom-right clock/timer visibly changes throughout the clip.

The local E2E harness writes under:

```text
artifacts/e2e/
```

## Limitations

- Canvas/output/FPS is global OBS video state, not scene-local state. This POC sets OBS to `3840x2160@30` because issue #1 requires it.
- OBS must provide the standard Windows `monitor_capture` input kind and the `browser_source` plugin.
- StreamOps auto-selects a non-`DUMMY` OBS display for desktop capture and uses DXGI capture for this POC.
- Scene layout can be applied while sources are inactive or reporting runtime size `0x0`; overlay sizing uses OBS bounds rather than live frame dimensions.
- Unmanaged items inside `gaming-poc` are disabled, not deleted, so stale sources cannot cover the desktop POC.
- This host currently needs Python installed before the CLI can run.

## Backlog

- Add a real dry-run/diff command before apply.
- Add a deploy wrapper for `C:\Scripts\streamops` after the runtime install path is agreed.
- Add worker/job support before implementing longer recording or livestream orchestration tasks.
