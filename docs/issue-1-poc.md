# Issue #1 POC Handoff

## Implemented

- `streamops scene apply gaming-poc` reconciles the managed OBS scene from `config/scenes/gaming-poc.yaml`.
- `streamops scene review gaming-poc` verifies the scene and writes review artifacts under `artifacts/gaming-poc/<timestamp>/`.
- `streamops scene review gaming-poc --video 15` records an optional sample video when OBS is not already streaming or recording.
- The POC reuses existing OBS sources `SRC-D4` and `OpenStream V8`; it does not create duplicate inputs.

## Reviewer Commands

```powershell
python -m pip install -e ".[dev]"
$env:OBS_WEBSOCKET_HOST = "127.0.0.1"
$env:OBS_WEBSOCKET_PORT = "4455"
$env:OBS_WEBSOCKET_PASSWORD = "<password-if-enabled>"

streamops scene apply gaming-poc
streamops scene review gaming-poc
streamops scene review gaming-poc --video 15
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

## Limitations

- Canvas/output/FPS is global OBS video state, not scene-local state. This POC sets OBS to `3840x2160@30` because issue #1 requires it.
- The configured OBS sources must already exist. Camera transport from device D is intentionally out of scope.
- Visible unmanaged items inside `gaming-poc` are preserved and reported as warnings instead of being deleted.
- This host currently needs Python installed before the CLI can run.

## Backlog

- Add a real dry-run/diff command before apply.
- Add a deploy wrapper for `C:\Scripts\streamops` after the runtime install path is agreed.
- Add worker/job support before implementing longer recording or livestream orchestration tasks.
