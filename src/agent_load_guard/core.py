from __future__ import annotations

try:
    import fcntl
except ImportError:  # Windows is not supported in this release.
    fcntl = None  # type: ignore[assignment]
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import time
from typing import Any, Sequence

import psutil

BUSY_EXIT = 75
DEFAULT_MEMORY_ESTIMATE_GIB = 3.0
DEFAULT_DISK_ESTIMATE_GIB = 1.0
DEFAULT_MEMORY_RESERVE_GIB = 3.0
DEFAULT_DISK_RESERVE_GIB = 8.0
GIB = 1024 ** 3


class GuardError(Exception):
    """An operational error safe to show without child command output."""


def default_state_dir() -> Path:
    override = os.environ.get("AGENT_LOAD_GUARD_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "agent-load-guard"
    cache_home = os.environ.get("XDG_CACHE_HOME")
    return (Path(cache_home).expanduser() if cache_home else Path.home() / ".cache") / "agent-load-guard"


def resource_snapshot(disk_path: str = ".") -> dict[str, float]:
    if sys.platform not in ("darwin", "linux"):
        raise GuardError("This release supports macOS and Linux.")
    try:
        memory = psutil.virtual_memory()
        disk = shutil.disk_usage(Path(disk_path).expanduser())
    except (OSError, ValueError) as exc:
        raise GuardError("Could not read memory or disk availability.") from exc
    return {
        "memory_available_gib": round(memory.available / GIB, 2),
        "memory_total_gib": round(memory.total / GIB, 2),
        "disk_free_gib": round(disk.free / GIB, 2),
    }


def admission(snapshot: dict[str, float], memory_gib: float, disk_gib: float,
              reserve_memory_gib: float, reserve_disk_gib: float) -> list[str]:
    reasons: list[str] = []
    if snapshot["memory_available_gib"] < memory_gib + reserve_memory_gib:
        reasons.append("memory_headroom_below_estimate_and_reserve")
    if snapshot["disk_free_gib"] < disk_gib + reserve_disk_gib:
        reasons.append("disk_headroom_below_estimate_and_reserve")
    return reasons


def read_owner(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def write_owner(path: Path, payload: dict[str, Any]) -> None:
    temp = path.with_name("owner.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _lock_file(state_dir: Path):
    if sys.platform not in ("darwin", "linux"):
        raise GuardError("This release supports macOS and Linux.")
    state_dir.mkdir(parents=True, exist_ok=True)
    return (state_dir / "heavy-command.lock").open("a+")


def _try_lock(lock) -> bool:
    if fcntl is None:
        raise GuardError("This release supports macOS and Linux.")
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False


def status(state_dir: Path, disk_path: str, memory_gib: float, disk_gib: float,
           reserve_memory_gib: float, reserve_disk_gib: float) -> tuple[dict[str, Any], int]:
    owner_path = state_dir / "owner.json"
    try:
        lock = _lock_file(state_dir)
    except OSError as exc:
        raise GuardError("Could not open the local guard state directory.") from exc
    with lock:
        active = not _try_lock(lock)
        try:
            snapshot = resource_snapshot(disk_path)
        except GuardError as exc:
            if not active:
                return {"status": "error", "error": str(exc)}, 1
            snapshot = None
        owner = read_owner(owner_path)
        if active:
            return {"status": "busy", "active": owner, "resources": snapshot}, 0
        reasons = admission(snapshot, memory_gib, disk_gib, reserve_memory_gib, reserve_disk_gib) if snapshot else []
        result = {
            "status": "ready" if not reasons else "deferred",
            "resources": snapshot,
            "request": {"memory_gib": memory_gib, "disk_gib": disk_gib,
                        "reserve_memory_gib": reserve_memory_gib,
                        "reserve_disk_gib": reserve_disk_gib},
            "reasons": reasons,
            "last_run": owner,
        }
        return result, 0


def run(command: Sequence[str], state_dir: Path, disk_path: str, owner: str,
        memory_gib: float, disk_gib: float, reserve_memory_gib: float,
        reserve_disk_gib: float) -> int:
    if not command:
        raise GuardError("Provide a command after --.")
    owner_path = state_dir / "owner.json"
    try:
        lock = _lock_file(state_dir)
    except OSError as exc:
        raise GuardError("Could not open the local guard state directory.") from exc
    with lock:
        if not _try_lock(lock):
            print(json.dumps({"status": "busy", "active": read_owner(owner_path),
                              "child_started": False}, ensure_ascii=False), flush=True)
            return BUSY_EXIT
        snapshot = resource_snapshot(disk_path)
        reasons = admission(snapshot, memory_gib, disk_gib, reserve_memory_gib, reserve_disk_gib)
        if reasons:
            print(json.dumps({"status": "deferred", "resources": snapshot,
                              "request": {"memory_gib": memory_gib, "disk_gib": disk_gib,
                                          "reserve_memory_gib": reserve_memory_gib,
                                          "reserve_disk_gib": reserve_disk_gib},
                              "reasons": reasons, "child_started": False}, ensure_ascii=False), flush=True)
            return BUSY_EXIT

        record: dict[str, Any] = {
            "owner": owner,
            "command": Path(command[0]).name,
            "runner_pid": os.getpid(),
            "started_at": time.time(),
            "status": "running",
        }
        write_owner(owner_path, record)
        print(json.dumps({"status": "running", "owner": owner,
                          "command": record["command"], "resources": snapshot}, ensure_ascii=False), flush=True)
        try:
            child = subprocess.Popen(command, pass_fds=(lock.fileno(),), start_new_session=True)
        except OSError as exc:
            record.update(status="failed_to_start", error=type(exc).__name__, finished_at=time.time())
            write_owner(owner_path, record)
            print(json.dumps({"status": "failed_to_start", "error": type(exc).__name__}, ensure_ascii=False), flush=True)
            return 127

        previous_handlers: dict[int, Any] = {}
        def forward(signum: int, _frame: Any) -> None:
            if child.poll() is None:
                try:
                    os.killpg(child.pid, signum)
                except ProcessLookupError:
                    pass

        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            previous_handlers[sig] = signal.signal(sig, forward)
        try:
            exit_code = child.wait()
        finally:
            for sig, handler in previous_handlers.items():
                signal.signal(sig, handler)
        record.update(status="finished", exit_code=exit_code, finished_at=time.time())
        write_owner(owner_path, record)
        print(json.dumps({"status": "finished", "owner": owner,
                          "command": record["command"], "exit_code": exit_code}, ensure_ascii=False), flush=True)
        return exit_code
