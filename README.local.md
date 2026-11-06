# 本地 Claude、Codex 和 DSH 群聊

这是 [bcurts/agentchattr](https://github.com/bcurts/agentchattr) 的轻量 fork，保留 MIT 许可证和上游功能。

## 安装与启动（macOS / Linux）

先安装 Python 3.11+、tmux、Claude Code 和 Codex CLI，并分别完成 CLI 登录。已有订阅/账号继续由各自 CLI 使用，本项目不接管登录凭证。

```sh
# macOS
brew install tmux
# uv 已安装时：
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r requirements.txt

# 同时启动网页、Claude 和 Codex，默认使用 data/workspace 独立目录
.venv/bin/python room.py start
# 或指定项目与参与者（与上一条二选一）
.venv/bin/python room.py start --cwd /path/to/project --agents claude codex
```

打开 <http://127.0.0.1:8300>，发 `@claude @codex` 消息即可邀请双方。顶栏状态按钮可改名和分配角色；Sessions 支持 Code Review、Design Critique、Planning、Debate，可选择参与会话的在线 Agent。新增多实例仍可使用上游 `wrapper.py`。

## 接入已部署的 DSH

先在本机启动并配置好 DeepSeek Harness Web 服务（默认 <http://127.0.0.1:3080>），然后选择 DSH 一起启动房间：

```sh
.venv/bin/python room.py start --agents claude codex dsh
# 也可只启动 DSH 房间
.venv/bin/python room.py start --agents dsh
# 已有房间正在运行时，先 room.py stop，再选参与者重启；不会停止 DSH 服务。
```

在网页发 `@dsh`，或者在 Sessions 的角色选择中选 DSH。适配器复用现有 DSH 服务的模型和凭证配置，不要求 OpenAI-compatible 接口，不另起 Harness。只允许回环 HTTP 地址，拒绝重定向。

普通频道各自绑定独立具名 DSH 会话；每次结构化评审使用新的会话标识，同一评审的后续阶段复用它。绑定保存在忽略的 `data/*-dsh-sessions.json`，重启可复用。新任务请开新频道或新评审，避免把不同主题混在普通频道的一段历史中。不会接管你已有的其他 DSH 会话。

适配器只提交队列消息并读取会话历史，等待当前整轮 `turn/end` 成功后才把最后的文本回写群聊。不会把中途的工具前说明当最终回复，也不会自动回答工具审批；需要审批或提问时，在 DSH 原页面处理。忙碌会话不强插、不取消；超时或网络结果不确定时保留请求 ID，不自动重发。查看桥接日志：

```sh
tmux -L agentchattr-room attach -t agentchattr-room-dsh
```

本次支持文字频道与 Sessions 的文本评审。Jobs 线程暂不接入，也不转发附件。停止房间会停掉桥接，保留历史和绑定；已经交给 DSH 的任务仍由 DSH 管理，不会被强制取消。

Claude/Codex 接入时新建 **CLI 会话**，不会自动接管 Codex 桌面当前聊天。需延续已有 CLI 会话时，可单独运行 wrapper 并传入 CLI 自身的 resume 参数；不要把当前正在工作的会话重复拉起。

```sh
.venv/bin/python room.py status
tmux -L agentchattr-room attach -t agentchattr-room-claude
tmux -L agentchattr-room attach -t agentchattr-room-codex
# 离开终端但保持运行：Ctrl+B，再按 D
.venv/bin/python room.py stop
```

首次启动的项目信任和工具审批在对应 tmux 终端中处理。启动器明确使用 Claude 默认权限、Codex workspace-write + untrusted 审批；不自动放行执行和 MCP 工具。多个 Agent 编辑同一项目仍需分工或独立 worktree，角色标签不是文件隔离。

模型默认沿用 CLI 配置。如果账号不支持全局配置的模型，在 Codex 终端用 `/model` 查看可用项，或者启动时传 `--codex-model <可用模型>`。也可在本地忽略文件 `config.local.toml` 中设置 `[room]` 的 `codex_model = "可用模型"`，只作用于本房间，不改全局配置。账号额度用完仍遵守各自服务的限制。

启动器仅管理一个使用默认端口的本地房间；端口或同名会话被占用时拒绝启动，不接管已有服务。停止仅作用于本次启动记录中的 tmux 会话，不删除聊天历史。关闭终端窗口不会自动停止房间。自定义端口、多房间、其他 CLI 请使用上游入口。

`data/`、`uploads/`、`.venv/`、`config.local.toml` 保持 gitignore，聊天、MCP 临时配置和个人项目路径不提交到 GitHub。Web/MCP 仅监听本机回环地址，不提供远程共享。

## 本 fork 的增量

- `room.py`：通过 tmux 一次启动、查看、停止 Claude/Codex/DSH 房间，选择参与者和项目目录。
- `wrapper.py --cwd`：按调用覆盖工作目录，不修改全局 MCP 配置。
- `dsh_bridge.py` 与 API wrapper 的 DSH 传输：复用已有 Harness，按频道/评审绑定独立会话，整轮完成后回写。
- 保留上游群聊、路由和评审模板；不重写 Agent 框架。

```sh
.venv/bin/python -m unittest discover -s tests
```
