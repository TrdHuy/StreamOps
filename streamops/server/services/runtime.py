"""Runtime ownership and discovery for lifecycle scripts."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
import json
import os
from pathlib import Path

from ..config import ServerConfig
from ..errors import RuntimeStateError
from ..platform.windows import desktop_session_info


class RuntimeLease:
    def __init__(self, path: Path, pid: int) -> None:
        self.path = path
        self.pid = pid

    @classmethod
    def acquire(cls, config: ServerConfig) -> "RuntimeLease":
        config.data_dir.mkdir(parents=True, exist_ok=True)
        path = config.data_dir / "runtime.json"
        pid = os.getpid()
        session = desktop_session_info()
        payload = {
            "pid": pid,
            "started_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "session_id": session.current_session_id,
            "active_console_session_id": session.active_console_session_id,
            **{key: str(value) if isinstance(value, Path) else value for key, value in asdict(config).items()},
        }
        encoded = (json.dumps(payload, indent=2) + "\n").encode("utf-8")

        for _ in range(2):
            try:
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
            except FileExistsError:
                existing_pid = _read_pid(path)
                if existing_pid is None:
                    raise RuntimeStateError(
                        f"Runtime state is invalid; inspect or remove it explicitly: {path}"
                    )
                if _pid_exists(existing_pid):
                    raise RuntimeStateError(
                        f"Another streamops-node process is already using {config.data_dir} (PID {existing_pid})."
                    )
                path.unlink(missing_ok=True)
                continue
            except OSError as exc:
                raise RuntimeStateError(f"Could not create runtime state: {path}") from exc
            else:
                with os.fdopen(descriptor, "wb") as output:
                    output.write(encoded)
                    output.flush()
                    os.fsync(output.fileno())
                return cls(path, pid)

        raise RuntimeStateError(f"Could not acquire runtime state: {path}")

    def release(self) -> None:
        if _read_pid(self.path) == self.pid:
            self.path.unlink(missing_ok=True)


def _read_pid(path: Path) -> int | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get("pid")
        return int(value)
    except (OSError, ValueError, TypeError, json.JSONDecodeError, AttributeError):
        return None


def _pid_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        process = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not process:
            return False
        ctypes.windll.kernel32.CloseHandle(process)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
