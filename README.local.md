# 本地 Claude + Codex 群聊

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

这是新建的 **CLI 会话**，不会自动接管 Codex 桌面当前聊天。需延续已有 CLI 会话时，可单独运行 wrapper 并传入 CLI 自身的 resume 参数；不要把当前正在工作的会话重复拉起。

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

- `room.py`：通过 tmux 一次启动、查看、停止 Claude/Codex 房间，选择参与者和项目目录。
- `wrapper.py --cwd`：按调用覆盖工作目录，不修改全局 MCP 配置。
- 保留上游群聊、路由和评审模板；不重写 Agent 框架。

```sh
.venv/bin/python -m unittest discover -s tests
```
