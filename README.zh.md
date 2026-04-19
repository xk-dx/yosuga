# yosuga

`yosuga` 是一个面向工作区的最小化编码agent。它提供 CLI 对话循环、模型后端适配、工具执行、策略控制、会话日志、回合报表，以及在系统提示词中注入技能元数据的 skills 机制。

## 项目定位

这个仓库是一个参考 Claude Code 思路的个人复刻项目。

- 不是 Claude Code 官方实现。
- 目标是用一个尽量小而清晰的代码库复现核心运行机制。
- 功能覆盖是阶段性的，会持续迭代完善。

## 项目做了什么

- 从当前工作区启动交互式 CLI agent。
- 支持 OpenAI-compatible、Anthropic-compatible 和 mock 三种模型后端。
- 提供工作区工具：`read_file`、`write_file`、`edit_file`、`list_dir`、`bash`、`list_skills`、`use_skill`、`grep`，`glob`。
- 在工具执行前做策略检查、用户确认、重试和熔断控制。
- 将会话日志和每轮统计报表分开保存。
- 启动时加载工程化系统提示词和 skills 元数据索引。

## 目录结构

- `main.py` - 本地运行入口。
- `src/yosuga/surfaces/cli/app.py` - CLI 启动与交互循环。
- `src/yosuga/runtime/kernel.py` - 回合编排、工具分发和报表写入。
- `src/yosuga/models/` - OpenAI、Anthropic 和 mock 模型适配器。
- `src/yosuga/tools/runtime.py` - 默认工具注册表。
- `src/yosuga/config/` - 路径、策略、会话日志、skills 和系统提示词构建。
- `src/yosuga/runtime/report.py` - 回合报表写入器。

## 快速开始

在仓库根目录运行：

```bash
python main.py
```

也可以显式指定后端：

```bash
python main.py --model mock
python main.py --model openai (推荐)
python main.py --model anthropic
```

如果不传 `--model`，启动器会根据环境变量自动探测，可用时优先使用真实后端，否则回退到 mock。

## 工作区参数

默认把当前目录当作工作区根目录。你也可以手动指定：

```bash
python main.py --workspace e:\projects\ai_project\some-workspace
```

所有工具都会在这个工作区根目录下操作。
## 会话恢复

支持恢复特定项目会话记忆

```bash
python main.py  --workspace e:\projects\ai_project\some-workspace --resume <session_id>
```


## 环境变量

运行时会读取这些环境变量：

可选
- `yosuga_WORKSPACE_ROOT` - 工作区根目录，供提示词构建和运行时使用。
- `yosuga_PROJECT_ROOT` - 项目根目录，供策略和提示词资产使用。

会话内角色切换：
- 使用 `/role <name>` 在当前会话中切换角色指令（例如 `/role lead`）。

必填
- `OPENAI_API_BASE` - Anthropic API 地址。
- `OPENAI_API_KEY` - OpenAI-compatible 后端密钥。
- `OPENAI_MODEL` - OpenAI-compatible 模型名。
- `ANTHROPIC_API_BASE` - Anthropic API 地址。
- `ANTHROPIC_API_KEY` - Anthropic API 密钥。
- `ANTHROPIC_MODEL` - Anthropic 模型名。

如果安装了 `python-dotenv`，启动器会自动尝试加载 `.env` 文件。

## Skills 机制

系统提示词会注入来自 `.yosuga/skills` 的技能元数据索引。运行时流程是：

1. 启动时只加载简洁的技能索引。
2. 模型需要时可以调用 `list_skills` 查看技能列表。
3. 模型可以调用 `use_skill` 读取某个技能的完整 `SKILL.md`。
4. 技能中的脚本可以通过正常的工具流程执行。

这样可以减少启动上下文的 token 占用，同时保留完整技能文档的按需加载能力。

## 日志与报表

每个会话都会生成一个独立目录，其中包含：

- `session.jsonl` - 会话事件日志。
- `report.jsonl` - 每回合统计报表。

报表当前会统计模型调用次数、token 使用量、工具成功和失败次数、重试次数，以及模型侧工具参数校验错误。

## 策略与安全

所有工具调用都会先经过策略规则检查。某些调用会要求用户确认；如果某个工具连续失败过多，也会暂时进入熔断状态。

## 当前状态

这个项目已经可以作为一个可用的 CLI agent runtime 来运行，但整体仍在继续迭代。

### 已实现

- 交互式 CLI 循环。
- Anthropic、OpenAI-compatible 和 mock 三种模型适配。
- 文件、目录、shell 和 skills 工具注册。
- 策略检查、用户确认、重试和熔断。
- 会话日志和每回合报表。
- 系统提示词构建与 skills 元数据注入。
- 短期记忆（会话级别上下文三级压缩）

### 未实现 / 进行中

- Memory 系统（规划中）：
	- 增加持久化记忆分层（user/session/repo）及读取/回写策略。
	- 将记忆召回接入回合规划与系统提示词构建流程。
	- 增加记忆安全规则（脱敏、容量限制、冲突处理）。
- Multi-Agent 系统（规划中）：
	- 增加 coordinator-worker 编排，用于任务拆解与并行执行。
	- 定义 agent 角色、交接协议与共享上下文契约。
	- 增加多 agent 输出的聚合与冲突消解机制。

## 备注

- 工作区默认只允许在配置好的根目录内写入。
- 项目运行时统一使用 `yosuga` 这个命名。
