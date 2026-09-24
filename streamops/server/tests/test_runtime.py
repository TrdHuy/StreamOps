from __future__ import annotations

import json
from pathlib import Path

import pytest

from streamops.server.config import ServerConfig
from streamops.server.errors import RuntimeStateError
from streamops.server.services.runtime import RuntimeLease


def test_runtime_lease_records_effective_config(server_config: ServerConfig) -> None:
    lease = RuntimeLease.acquire(server_config)
    try:
        state = json.loads(lease.path.read_text(encoding="utf-8"))
        assert state["pid"] == lease.pid
        assert state["port"] == 8765
        assert state["data_dir"] == str(server_config.data_dir)
        assert isinstance(state["session_id"], int)
        assert isinstance(state["active_console_session_id"], int)
    finally:
        lease.release()

    assert not lease.path.exists()


def test_runtime_lease_rejects_live_owner(server_config: ServerConfig) -> None:
    lease = RuntimeLease.acquire(server_config)
    try:
        with pytest.raises(RuntimeStateError, match="already using"):
            RuntimeLease.acquire(server_config)
    finally:
        lease.release()


def test_runtime_lease_replaces_stale_owner(server_config: ServerConfig, monkeypatch) -> None:
    runtime_path = server_config.data_dir / "runtime.json"
    server_config.data_dir.mkdir(parents=True, exist_ok=True)
    runtime_path.write_text(json.dumps({"pid": 99999999}), encoding="utf-8")
    monkeypatch.setattr("streamops.server.services.runtime._pid_exists", lambda _pid: False)

    lease = RuntimeLease.acquire(server_config)
    try:
        assert json.loads(runtime_path.read_text(encoding="utf-8"))["pid"] == lease.pid
    finally:
        lease.release()


def test_runtime_path_stays_in_data_directory(server_config: ServerConfig) -> None:
    lease = RuntimeLease.acquire(server_config)
    try:
        assert lease.path.parent == Path(server_config.data_dir)
    finally:
        lease.release()
