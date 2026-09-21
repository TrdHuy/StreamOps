# StreamOps Agent Notes

- Treat this repository as the source of truth for OBS/livestream automation.
- Prefer desired-state config plus idempotent apply/verify logic over one-off scripts.
- Never commit OBS WebSocket passwords, stream keys, SSH keys, or generated review artifacts.
- Do not delete OBS scenes, inputs, profiles, or runtime scripts unless the operator explicitly approves it.
- Preserve existing files under `C:\Scripts`; use explicit deploy/install steps instead of overwriting runtime commands.
- For OBS changes, inspect current state, apply the minimum required mutation, verify, and leave reviewable evidence.
