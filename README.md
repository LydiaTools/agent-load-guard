# Agent Load Guard

**A tiny local gate for heavy AI coding jobs.** Keep a parallel Codex or Claude Code queue from starting another resource-heavy command when the machine is already busy.

`agent-load-guard` checks available memory and disk, then gives one cooperative command a shared local slot. If the slot is occupied or your requested headroom is unavailable, it returns a clear JSON `busy` or `deferred` result without starting the command.

## Why this exists

Coding agents make parallel work easy. Running several builds, tests, or headless agent jobs at once can make a local machine run out of memory or disk space. Agent Load Guard is a small admission gate for commands you choose to launch through it. It is not another agent dashboard.

## Install

Clone the repository and install the local package:

```bash
git clone https://github.com/LydiaTools/agent-load-guard.git
cd agent-load-guard
python3 -m pip install .
```

The GitHub Releases page also provides a wheel and its SHA-256 checksum.

Install the current v0.1.0 wheel directly:

```bash
python3 -m pip install https://github.com/LydiaTools/agent-load-guard/releases/download/v0.1.0/agent_load_guard-0.1.0-py3-none-any.whl
```

## Try it

Check the current machine and whether a default job fits:

```bash
agent-load-guard status
```

Run a heavy command through the shared slot:

```bash
agent-load-guard run --owner codex-integration-tests \
  --memory-gib 3 --disk-gib 1 \
  --reserve-memory-gib 3 --reserve-disk-gib 8 \
  -- python -m unittest discover -s tests
```

The estimates are supplied by you. On success, the child command runs and the slot stays occupied until it exits. A second guarded command exits with code `75` and does not start. A resource check failure also exits with code `75`; command errors keep their original exit code.

After installing from this checkout, run the real two-process demo:

```bash
python3 examples/concurrency_demo.py
```

It starts one short-lived child, then tries to start another through the same isolated state directory. The demo verifies the second result is `busy`, exit code `75`, and that the blocked child did not run. No agent session, API key, or network request is involved.

## Works with any command

The guard is deliberately outside the agent runtime. Wrap a Codex CLI, Claude Code CLI, build, test, or export command that you start yourself:

```bash
agent-load-guard run --owner codex-task --memory-gib 4 --disk-gib 2 -- codex exec "Run the requested task"
```

Use a short, non-sensitive owner label. The guard stores the label, executable name, runner PID, timestamps, and exit status. It does not store the command arguments, prompts, API keys, or child output.

## What it does and does not do

- Coordinates one heavy command slot for processes that share the same local state directory.
- Checks host-available memory and free disk against your estimate plus a reserve.
- Starts no child process when another guarded job is running or the requested headroom is missing.
- Never kills, restarts, or changes existing processes or agent configuration.
- Works on macOS and Linux in this release. Windows is not supported yet.

It cannot control desktop-agent sessions or commands started outside the guard. Estimates do not enforce the command's actual memory or disk use, and the guard cannot diagnose or fix an upstream agent memory leak. An unguarded process can still consume resources while a guarded command runs.

## Development

```bash
python3 -m pip install -e .
python3 -m unittest discover -s tests -v
```

## License

MIT. This is an independent community utility and is not affiliated with OpenAI, Anthropic, or any agent vendor.
