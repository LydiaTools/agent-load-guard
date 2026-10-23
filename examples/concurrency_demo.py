from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
GUARD = [sys.executable, "-m", "agent_load_guard.cli"]
RESOURCE_ARGS = [
    "--memory-gib", "0",
    "--disk-gib", "0",
    "--reserve-memory-gib", "0",
    "--reserve-disk-gib", "0",
]


def guarded_command(owner: str, state_dir: Path, child: list[str]) -> list[str]:
    return [
        *GUARD,
        "run",
        "--owner", owner,
        *RESOURCE_ARGS,
        "--state-dir", str(state_dir),
        "--",
        *child,
    ]


def main() -> int:
    if sys.platform not in ("darwin", "linux"):
        print("This demo requires macOS or Linux.", file=sys.stderr)
        return 2

    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(SOURCE), env.get("PYTHONPATH", "")) if part
    )

    with tempfile.TemporaryDirectory(prefix="agent-load-guard-demo-") as temp:
        state_dir = Path(temp) / "state"
        blocked_marker = Path(temp) / "blocked-child-started"
        running_marker = Path(temp) / "first-child-started"
        release_marker = Path(temp) / "release-first-child"
        marker_code = (
            "from pathlib import Path; "
            f"Path({str(blocked_marker)!r}).write_text('started', encoding='utf-8')"
        )
        wait_code = "\n".join(
            [
                "from pathlib import Path",
                "import time",
                f"Path({str(running_marker)!r}).write_text('started', encoding='utf-8')",
                f"release = Path({str(release_marker)!r})",
                "deadline = time.monotonic() + 20",
                "while not release.exists() and time.monotonic() < deadline:",
                "    time.sleep(0.02)",
                "raise SystemExit(0 if release.exists() else 1)",
            ]
        )

        first = subprocess.Popen(
            guarded_command(
                "demo-active",
                state_dir,
                [sys.executable, "-c", wait_code],
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            start_new_session=True,
        )
        try:
            first_line = first.stdout.readline() if first.stdout else ""
            if not first_line:
                _stdout, stderr = first.communicate(timeout=5)
                raise RuntimeError(f"first command did not start: {stderr.strip()}")
            first_event = json.loads(first_line)
            if first_event.get("status") != "running":
                raise RuntimeError(f"first command was not admitted: {first_event}")
            child_deadline = time.monotonic() + 5
            while (
                not running_marker.exists()
                and first.poll() is None
                and time.monotonic() < child_deadline
            ):
                time.sleep(0.02)
            if not running_marker.exists():
                raise RuntimeError("first child did not reach its running state")

            second = subprocess.run(
                guarded_command(
                    "demo-contender",
                    state_dir,
                    [sys.executable, "-c", marker_code],
                ),
                capture_output=True,
                text=True,
                env=env,
                check=False,
                timeout=5,
            )
            second_event = json.loads(second.stdout)
            release_marker.write_text("release", encoding="utf-8")
            _first_tail, first_stderr = first.communicate(timeout=5)

            if first.returncode != 0:
                raise RuntimeError(f"first command failed: {first_stderr.strip()}")
            if (
                second.returncode != 75
                or second_event.get("status") != "busy"
                or second_event.get("child_started") is not False
                or blocked_marker.exists()
            ):
                raise RuntimeError(
                    "second command was not safely blocked: "
                    f"exit={second.returncode}, result={second_event}, "
                    f"marker_exists={blocked_marker.exists()}"
                )

            print(f"first: {first_event['status']} owner={first_event['owner']}")
            print(
                "second: "
                f"{second_event['status']} "
                f"child_started={str(second_event['child_started']).lower()} "
                f"exit={second.returncode}"
            )
            print("verified: the blocked child's marker was not created")
            return 0
        finally:
            release_marker.write_text("release", encoding="utf-8")
            if first.poll() is None:
                try:
                    os.killpg(first.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    first.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(first.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    first.wait(timeout=5)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        OSError,
        RuntimeError,
        json.JSONDecodeError,
        subprocess.TimeoutExpired,
        subprocess.CalledProcessError,
    ) as exc:
        print(f"demo failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
