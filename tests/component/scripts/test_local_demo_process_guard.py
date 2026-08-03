"""Regression coverage for the local-demo stop script's process ownership guard."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
from pathlib import Path
from time import sleep
from typing import Any

import pytest

ROOT = Path(__file__).parents[3]
STOP_SCRIPT = ROOT / "scripts" / "stop_local_demo.ps1"
PROCESS_EXECUTABLE = str(Path(getattr(sys, "_base_executable", sys.executable)))


def _available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _listener_process(port: int, token: str) -> subprocess.Popen[str]:
    listener_code = (
        "import socket,time; "
        "listener=socket.socket(); "
        "listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1); "
        f"listener.bind(('127.0.0.1',{port})); listener.listen(); time.sleep(60)"
    )
    return subprocess.Popen(
        [
            PROCESS_EXECUTABLE,
            "-c",
            listener_code,
            "--demo-token",
            token,
            "--demo-repository",
            str(ROOT),
        ],
        text=True,
    )


def _record(
    backend: subprocess.Popen[Any],
    frontend: subprocess.Popen[Any],
    backend_port: int,
    frontend_port: int,
    token: str,
) -> dict[str, object]:
    return {
        "record_version": 2,
        "session_token": token,
        "repository_root": str(ROOT),
        "backend_process_id": backend.pid,
        "backend_executable_path": PROCESS_EXECUTABLE,
        "backend_port": backend_port,
        "frontend_process_id": frontend.pid,
        "frontend_executable_path": PROCESS_EXECUTABLE,
        "frontend_port": frontend_port,
    }


def _stop(record_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(STOP_SCRIPT),
            "-ProcessFile",
            str(record_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _terminate(process: subprocess.Popen[Any]) -> None:
    if process.poll() is None:
        process.terminate()
        process.wait(timeout=10)


def test_stop_script_does_not_kill_a_process_with_a_forged_record(tmp_path: Path) -> None:
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    record_path = tmp_path / "forged.json"
    try:
        record_path.write_text(
            json.dumps(_record(unrelated, unrelated, 49111, 49112, "forged-session-token")),
            encoding="utf-8",
        )

        result = _stop(record_path)

        assert unrelated.poll() is None
        assert "Did not stop" in result.stdout
        assert not record_path.exists()
    finally:
        _terminate(unrelated)


def test_stop_script_rejects_malformed_and_stale_records(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.json"
    malformed.write_text("not-json", encoding="utf-8")

    malformed_result = _stop(malformed)

    assert malformed_result.returncode == 1
    assert "no process was stopped" in malformed_result.stdout
    assert not malformed.exists()

    stale = tmp_path / "stale.json"
    stale.write_text(
        json.dumps(
            {
                "record_version": 2,
                "session_token": "stale-token",
                "repository_root": str(ROOT),
                "backend_process_id": 999999,
                "backend_executable_path": sys.executable,
                "backend_port": 49113,
                "frontend_process_id": 999998,
                "frontend_executable_path": sys.executable,
                "frontend_port": 49114,
            }
        ),
        encoding="utf-8",
    )

    stale_result = _stop(stale)

    assert stale_result.returncode == 0
    assert "process_not_found" in stale_result.stdout
    assert not stale.exists()


def test_stop_script_ends_only_fully_verified_listener_processes(tmp_path: Path) -> None:
    token = "verified-session-token"
    backend_port = _available_port()
    frontend_port = _available_port()
    backend = _listener_process(backend_port, token)
    frontend = _listener_process(frontend_port, token)
    record_path = tmp_path / "verified.json"
    try:
        sleep(0.2)
        record_path.write_text(
            json.dumps(_record(backend, frontend, backend_port, frontend_port, token)),
            encoding="utf-8",
        )

        result = _stop(record_path)
        if "command_line_unavailable" in result.stdout:
            pytest.skip(
                "Windows process command-line inspection is unavailable in this environment"
            )

        backend.wait(timeout=10)
        frontend.wait(timeout=10)
        assert backend.returncode is not None
        assert frontend.returncode is not None
        assert not record_path.exists()
    finally:
        _terminate(backend)
        _terminate(frontend)
