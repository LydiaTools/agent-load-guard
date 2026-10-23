from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def cli_env(state_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    env["AGENT_LOAD_GUARD_DIR"] = str(state_dir)
    return env


class AgentLoadGuardTests(unittest.TestCase):
    def test_resource_estimate_requires_requested_headroom(self) -> None:
        from agent_load_guard.core import admission

        resources = {"memory_available_gib": 8.0, "memory_total_gib": 16.0, "disk_free_gib": 12.0}
        self.assertEqual(admission(resources, 3, 1, 3, 8), [])
        self.assertEqual(admission(resources, 6, 1, 3, 8), ["memory_headroom_below_estimate_and_reserve"])
        self.assertEqual(admission(resources, 3, 3, 3, 10), ["disk_headroom_below_estimate_and_reserve"])

    def test_insufficient_memory_does_not_start_child(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            state_dir = Path(temp) / "state"
            marker = Path(temp) / "child-started"
            result = subprocess.run(
                [sys.executable, "-m", "agent_load_guard.cli", "run", "--owner", "defer-test",
                 "--memory-gib", "1000000", "--disk-gib", "0", "--reserve-memory-gib", "0",
                 "--reserve-disk-gib", "0", "--", sys.executable, "-c",
                 f"from pathlib import Path; Path({str(marker)!r}).write_text('started')"],
                cwd=ROOT, env=cli_env(state_dir), capture_output=True, text=True, timeout=10,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(result.returncode, 75)
            self.assertEqual(payload["status"], "deferred")
            self.assertFalse(payload["child_started"])
            self.assertFalse(marker.exists())

    def test_busy_slot_blocks_second_process_and_releases_after_exit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            state_dir = Path(temp) / "state"
            common = ["--owner", "slot-test", "--memory-gib", "0", "--disk-gib", "0",
                      "--reserve-memory-gib", "0", "--reserve-disk-gib", "0"]
            first = subprocess.Popen(
                [sys.executable, "-m", "agent_load_guard.cli", "run", *common,
                 "--", sys.executable, "-c", "import time; time.sleep(0.7)"],
                cwd=ROOT, env=cli_env(state_dir), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            try:
                assert first.stdout is not None
                first_line = first.stdout.readline()
                self.assertEqual(json.loads(first_line)["status"], "running")
                second = subprocess.run(
                    [sys.executable, "-m", "agent_load_guard.cli", "run", *common,
                     "--", sys.executable, "-c", "raise SystemExit(99)"],
                    cwd=ROOT, env=cli_env(state_dir), capture_output=True, text=True, timeout=10,
                )
                payload = json.loads(second.stdout)
                self.assertEqual(second.returncode, 75)
                self.assertEqual(payload["status"], "busy")
                self.assertFalse(payload["child_started"])
                first_stdout, _ = first.communicate(timeout=10)
                self.assertEqual(first.returncode, 0)
                self.assertEqual(json.loads(first_stdout.splitlines()[-1])["status"], "finished")
            finally:
                if first.poll() is None:
                    first.terminate()
                    first.wait(timeout=5)

            after = subprocess.run(
                [sys.executable, "-m", "agent_load_guard.cli", "run", *common,
                 "--", sys.executable, "-c", "raise SystemExit(7)"],
                cwd=ROOT, env=cli_env(state_dir), capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(after.returncode, 7)
            self.assertEqual(json.loads(after.stdout.splitlines()[-1])["exit_code"], 7)


if __name__ == "__main__":
    unittest.main()
