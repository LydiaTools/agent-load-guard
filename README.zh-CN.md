# Agent Load Guard｜AI 编码任务资源闸门

**给重型 AI 编码任务加一道本地资源闸门。** 多个 Codex 或 Claude Code 命令并行时，避免再启动一个明显放不下的构建、测试或 CLI 任务。

`agent-load-guard` 会检查当前可用内存和磁盘，并让一个通过检查的命令占用共享本地任务位。如果任务位已被占用，或估算后无法保留足够资源，它会返回 JSON 格式的 `busy` / `deferred`，不会启动子进程。

## 为什么做它

编码 Agent 让并行工作变得容易，但同时跑多个构建、测试或无头 Agent 任务，也可能让本机内存或磁盘吃紧。这个小工具只负责协调你选择通过它启动的重型命令，不是另一个 Agent 看板。

## 安装

克隆仓库并安装本地包：

```bash
git clone https://github.com/LydiaTools/agent-load-guard.git
cd agent-load-guard
python3 -m pip install .
```

GitHub Releases 页面也会提供 wheel 安装包及其 SHA-256 校验值。

也可以直接安装 v0.1.0 wheel：

```bash
python3 -m pip install https://github.com/LydiaTools/agent-load-guard/releases/download/v0.1.0/agent_load_guard-0.1.0-py3-none-any.whl
```

## 试一下

查看当前资源和默认任务能否启动：

```bash
agent-load-guard status
```

通过共享任务位运行重型命令：

```bash
agent-load-guard run --owner codex-integration-tests \
  --memory-gib 3 --disk-gib 1 \
  --reserve-memory-gib 3 --reserve-disk-gib 8 \
  -- python -m unittest discover -s tests
```

内存和磁盘用量由你估算。通过检查后，子命令运行期间会一直占用任务位。第二个受控命令会以退出码 `75` 返回，不会启动；资源不足时也一样。子命令自身的退出码会原样返回。

安装并克隆本仓库后，运行真实的双进程演示：

```bash
python3 examples/concurrency_demo.py
```

它会先启动一个短任务，再通过同一个隔离状态目录启动第二个任务。演示会核对第二个结果为 `busy`、退出码为 `75`，且被拦截的子进程没有运行。不需要启动 Agent 会话、API Key 或网络请求。

实测输出：

```text
first: running owner=demo-active
second: busy child_started=false exit=75
verified: the blocked child's marker was not created
```

## 支持任意命令

资源闸门位于 Agent 运行环境之外，可包住 Codex CLI、Claude Code CLI、构建、测试或导出命令：

```bash
agent-load-guard run --owner codex-task --memory-gib 4 --disk-gib 2 -- codex exec "Run the requested task"
```

`owner` 请写简短且不含敏感信息的标签。工具只记录标签、可执行文件名、运行进程 ID、时间和退出状态；不记录完整命令参数、提示词、API Key 或子命令输出。

## 能做什么，不能做什么

- 在共享同一状态目录的进程间协调一个重型任务位。
- 按你填写的估算值与保留量检查当前可用内存和磁盘。
- 任务位已占用或资源不足时，不启动新子进程。
- 不会杀死、重启或改动已有进程和 Agent 配置。
- 当前版本支持 macOS 和 Linux，暂不支持 Windows。

未通过本工具启动的桌面 Agent 会话和命令不受控制。估算值不能限制子命令的实际资源占用；工具也不能诊断或修复 Agent 上游的内存泄漏。其他未受控进程仍可能在任务运行期间消耗资源。

## 开发

```bash
python3 -m pip install -e .
python3 -m unittest discover -s tests -v
```

## 许可

MIT。本项目是独立社区工具，与 OpenAI、Anthropic 或任何 Agent 厂商无隶属关系。
