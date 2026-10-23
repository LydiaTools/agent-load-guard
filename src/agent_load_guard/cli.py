from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Sequence

from .core import (
    BUSY_EXIT,
    DEFAULT_DISK_ESTIMATE_GIB,
    DEFAULT_DISK_RESERVE_GIB,
    DEFAULT_MEMORY_ESTIMATE_GIB,
    DEFAULT_MEMORY_RESERVE_GIB,
    GuardError,
    default_state_dir,
    run,
    status,
)


def _non_negative_float(value: str) -> float:
    try:
        result = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if not math.isfinite(result) or result < 0:
        raise argparse.ArgumentTypeError("must be finite and non-negative")
    return result


def _resource_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--memory-gib", type=_non_negative_float, default=DEFAULT_MEMORY_ESTIMATE_GIB,
                        help="your estimate for this command's memory use (default: 3)")
    parser.add_argument("--disk-gib", type=_non_negative_float, default=DEFAULT_DISK_ESTIMATE_GIB,
                        help="your estimate for this command's disk use (default: 1)")
    parser.add_argument("--reserve-memory-gib", type=_non_negative_float, default=DEFAULT_MEMORY_RESERVE_GIB,
                        help="memory to leave available after the estimate (default: 3)")
    parser.add_argument("--reserve-disk-gib", type=_non_negative_float, default=DEFAULT_DISK_RESERVE_GIB,
                        help="disk space to leave free after the estimate (default: 8)")
    parser.add_argument("--disk-path", default=".", help="filesystem where the command will write (default: .)")
    parser.add_argument("--state-dir", type=Path, default=default_state_dir(),
                        help="shared local lock directory (default: user cache directory)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-load-guard",
        description="A cooperative local gate for resource-heavy commands.",
    )
    sub = parser.add_subparsers(dest="action", required=True)
    status_parser = sub.add_parser("status", help="show resources and whether a default job could start")
    _resource_options(status_parser)
    run_parser = sub.add_parser("run", help="run one command if the shared slot and resource check allow it")
    _resource_options(run_parser)
    run_parser.add_argument("--owner", required=True, help="short label shown by status; do not include secrets")
    run_parser.add_argument("command", nargs=argparse.REMAINDER, help="command after --")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.action == "status":
            payload, exit_code = status(args.state_dir, args.disk_path, args.memory_gib, args.disk_gib,
                                        args.reserve_memory_gib, args.reserve_disk_gib)
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            return exit_code
        command = list(args.command)
        if command[:1] == ["--"]:
            command = command[1:]
        return run(command, args.state_dir, args.disk_path, args.owner, args.memory_gib, args.disk_gib,
                   args.reserve_memory_gib, args.reserve_disk_gib)
    except GuardError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
