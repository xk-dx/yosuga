# Yosuga 工具使用示例文档

本文档介绍了 Yosuga 系统中可用的工具及其使用示例。

---

## 目录

1. [文件操作工具](#文件操作工具)
2. [目录操作工具](#目录操作工具)
3. [搜索工具](#搜索工具)
4. [Shell 命令工具](#shell-命令工具)
5. [技能系统工具](#技能系统工具)
6. [子代理工具](#子代理工具)

---

## 文件操作工具

### read_file - 读取文件内容

**功能**：读取指定路径的 UTF-8 文本文件内容，支持指定行范围。

**参数**：
- `path` (必需): 文件路径
- `start_line` (可选): 起始行号（从1开始）
- `end_line` (可选): 结束行号
- `max_lines` (可选): 最大读取行数，默认200
- `include_line_numbers` (可选): 是否包含行号

**使用示例**：

```python
# 读取整个文件
result = tool_registry.execute(ToolCall(
    name="read_file",
    input={"path": "src/main.py"}
))

# 读取特定行范围
result = tool_registry.execute(ToolCall(
    name="read_file",
    input={
        "path": "src/main.py",
        "start_line": 1,
        "end_line": 50,
        "include_line_numbers": True
    }
))

# 限制读取行数
result = tool_registry.execute(ToolCall(
    name="read_file",
    input={
        "path": "src/main.py",
        "max_lines": 100
    }
))
```

**策略检查**：
- 禁止读取 `.yosuga` 系统配置目录
- 读取大量内容时需要用户确认

---

### write_file - 写入文件

**功能**：将内容写入指定文件，可选择是否覆盖已有文件。

**参数**：
- `path` (必需): 目标文件路径
- `content` (必需): 要写入的内容
- `overwrite` (可选): 是否覆盖已有文件，默认 False

**使用示例**：

```python
# 创建新文件
result = tool_registry.execute(ToolCall(
    name="write_file",
    input={
        "path": "config/settings.json",
        "content": '{"debug": true, "port": 8080}'
    }
))

# 覆盖已有文件
result = tool_registry.execute(ToolCall(
    name="write_file",
    input={
        "path": "config/settings.json",
        "content": '{"debug": false, "port": 3000}',
        "overwrite": True
    }
))
```

**策略检查**：
- 路径必须在工作空间内
- 大文件写入需要用户确认
- 覆盖已有文件需要用户确认
- 受 mutation_mode 控制（allow/confirm/block）

---

### edit_file - 编辑文件

**功能**：在文件中替换指定的文本内容。

**参数**：
- `path` (必需): 目标文件路径
- `old_text` (必需): 要替换的旧文本
- `new_text` (必需): 新文本
- `replace_all` (可选): 是否替换所有匹配项，默认 False

**使用示例**：

```python
# 替换第一个匹配项
result = tool_registry.execute(ToolCall(
    name="edit_file",
    input={
        "path": "src/main.py",
        "old_text": "DEBUG = True",
        "new_text": "DEBUG = False"
    }
))

# 替换所有匹配项
result = tool_registry.execute(ToolCall(
    name="edit_file",
    input={
        "path": "src/utils.py",
        "old_text": "print(",
        "new_text": "logger.debug(",
        "replace_all": True
    }
))
```

**策略检查**：
- 路径必须在工作空间内
- 大文件编辑需要用户确认
- 受 mutation_mode 控制（allow/confirm/block）

---

## 目录操作工具

### list_dir - 列出目录内容

**功能**：列出指定目录下的所有条目。

**参数**：
- `path` (必需): 目录路径

**使用示例**：

```python
# 列出当前目录
result = tool_registry.execute(ToolCall(
    name="list_dir",
    input={"path": "."}
))

# 列出特定目录
result = tool_registry.execute(ToolCall(
    name="list_dir",
    input={"path": "src/components"}
))
```

**策略检查**：
- 禁止访问 `.yosuga` 系统配置目录
- 列出根目录可能需要用户确认

---

## 搜索工具

### glob - 文件模式匹配

**功能**：使用 glob 模式查找文件。

**参数**：
- `pattern` (可选): glob 匹配模式，默认 "*"
- `path` (可选): 搜索路径，默认 "."
- `include_dirs` (可选): 是否包含目录，默认 False
- `max_results` (可选): 最大结果数

**使用示例**：

```python
# 查找所有 Python 文件
result = tool_registry.execute(ToolCall(
    name="glob",
    input={
        "pattern": "**/*.py",
        "path": "src"
    }
))

# 查找特定目录下的配置文件
result = tool_registry.execute(ToolCall(
    name="glob",
    input={
        "pattern": "*.json",
        "path": "config",
        "max_results": 10
    }
))

# 包含目录的搜索
result = tool_registry.execute(ToolCall(
    name="glob",
    input={
        "pattern": "*",
        "path": "src",
        "include_dirs": True
    }
))
```

**策略检查**：
- 禁止在 `.yosuga` 目录中搜索

---

### grep - 文本搜索

**功能**：在文件中搜索指定的文本或正则表达式。

**参数**：
- `query` (必需): 搜索关键词或正则表达式
- `path` (可选): 搜索路径，默认 "."
- `is_regexp` (可选): 是否使用正则表达式，默认 False
- `case_sensitive` (可选): 是否区分大小写，默认 False
- `max_results` (可选): 最大结果数

**使用示例**：

```python
# 简单文本搜索
result = tool_registry.execute(ToolCall(
    name="grep",
    input={
        "query": "class ToolRegistry",
        "path": "src"
    }
))

# 正则表达式搜索
result = tool_registry.execute(ToolCall(
    name="grep",
    input={
        "query": "def \w+\(self",
        "path": "src/yosuga/tools",
        "is_regexp": True
    }
))

# 区分大小写的搜索
result = tool_registry.execute(ToolCall(
    name="grep",
    input={
        "query": "TODO",
        "path": "src",
        "case_sensitive": True,
        "max_results": 20
    }
))
```

**策略检查**：
- 禁止在 `.yosuga` 目录中搜索

---

## Shell 命令工具

### bash - 执行 Shell 命令

**功能**：执行 shell 命令并返回输出。

**参数**：
- `command` (必需): 要执行的命令

**使用示例**：

```python
# 查看当前目录
result = tool_registry.execute(ToolCall(
    name="bash",
    input={"command": "pwd"}
))

# 列出文件详情
result = tool_registry.execute(ToolCall(
    name="bash",
    input={"command": "ls -la"}
))

# 执行 Git 命令
result = tool_registry.execute(ToolCall(
    name="bash",
    input={"command": "git status"}
))

# 运行测试
result = tool_registry.execute(ToolCall(
    name="bash",
    input={"command": "python -m pytest tests/ -v"}
))
```

**策略检查**：
- 阻止包含危险操作的命令（如 rm -rf）
- 风险命令需要用户确认
- Windows 下自动转换 Unix 风格的 mkdir 命令

---

## 技能系统工具

### list_skills - 列出可用技能

**功能**：列出系统中可用的技能。

**参数**：
- `scope` (可选): 技能范围，可选 "all" 或 "workspace"，默认 "all"

**使用示例**：

```python
# 列出所有技能
result = tool_registry.execute(ToolCall(
    name="list_skills",
    input={"scope": "all"}
))

# 只列出工作空间技能
result = tool_registry.execute(ToolCall(
    name="list_skills",
    input={"scope": "workspace"}
))
```

---

### use_skill - 加载技能

**功能**：加载指定技能的完整文档和脚本列表。

**参数**：
- `skill` (必需): 技能名称或 slug
- `max_chars` (可选): 最大字符数，默认 200000

**使用示例**：

```python
# 加载特定技能
result = tool_registry.execute(ToolCall(
    name="use_skill",
    input={"skill": "python-testing"}
))

# 限制加载大小
result = tool_registry.execute(ToolCall(
    name="use_skill",
    input={
        "skill": "python-testing",
        "max_chars": 50000
    }
))
```

---

## 子代理工具

### spawn_subagent - 生成子代理

**功能**：生成一个具有独立上下文的子代理来执行任务。

**参数**：
- `task` (必需): 任务描述
- `role` (可选): 子代理角色，可选 "lead", "implementer", "researcher", "reviewer"，默认 "implementer"
- `max_iters` (可选): 最大迭代次数，默认 40
- `context` (可选): 传递给子代理的额外上下文

**使用示例**：

```python
# 简单任务委托
result = tool_registry.execute(ToolCall(
    name="spawn_subagent",
    input={
        "task": "分析 src/utils.py 中的函数复杂度，并提出优化建议"
    }
))

# 指定角色和上下文
result = tool_registry.execute(ToolCall(
    name="spawn_subagent",
    input={
        "task": "审查代码质量",
        "role": "reviewer",
        "max_iters": 20,
        "context": {
            "file": "src/main.py",
            "focus": "安全性检查"
        }
    }
))

# 研究任务
result = tool_registry.execute(ToolCall(
    name="spawn_subagent",
    input={
        "task": "研究最佳的重试策略实现方式",
        "role": "researcher",
        "context": {
            "current_impl": "简单的指数退避",
            "requirements": ["支持抖动", "可配置退避时间"]
        }
    }
))
```

**注意事项**：
- 子代理不能生成进一步的子代理（防止无限递归）
- 子代理运行独立的 TAOR 循环
- 只有最终结果会返回给父代理

---

## 工具策略引擎

### ToolPolicyEngine

`ToolPolicyEngine` 负责对所有工具调用进行安全策略检查。

**主要功能**：

1. **路径安全检查**：确保所有文件操作都在工作空间内
2. **命令安全检查**：阻止危险命令，标记风险命令
3. **内容大小检查**：大文件操作需要用户确认
4. **系统目录保护**：禁止访问 `.yosuga` 配置目录
5. **变更模式控制**：支持 allow/confirm/block 三种模式

**变更模式**：

```python
# 设置变更模式
engine.set_mutation_mode("confirm")  # 需要确认
engine.set_mutation_mode("allow")    # 自动允许
engine.set_mutation_mode("block")    # 阻止所有变更
```

**决策结果**：
- `allow`: 允许执行
- `ask_user`: 需要用户确认
- `block`: 阻止执行

---

## 工具注册表

### ToolRegistry

`ToolRegistry` 管理所有工具的注册和执行。

**主要功能**：

1. **工具注册**：注册新工具及其处理函数
2. **策略执行**：执行前进行策略检查
3. **审计日志**：记录所有工具调用
4. **熔断机制**：防止工具反复失败
5. **重试机制**：支持可重试错误的自动重试

**使用示例**：

```python
# 创建注册表
registry = ToolRegistry(
    root=Path("/workspace"),
    state_root=Path("/workspace/.yosuga")
)

# 设置变更模式
registry.set_mutation_mode("confirm")

# 执行工具调用
call = ToolCall(name="read_file", input={"path": "main.py"})
result = registry.execute(call)
```

---

## 最佳实践

1. **文件操作**：
   - 优先使用 `read_file` 的 `max_lines` 限制大文件读取
   - 使用 `edit_file` 进行精确修改，避免重写整个文件
   - 批量修改时使用 `replace_all=True`

2. **搜索操作**：
   - 使用 `glob` 查找文件结构
   - 使用 `grep` 查找代码内容
   - 合理设置 `max_results` 避免过多输出

3. **Shell 命令**：
   - 优先使用非破坏性命令（如 `dir`, `type`, `git status`）
   - 避免使用 `rm -rf` 等危险命令
   - Windows 环境下注意命令兼容性

4. **子代理**：
   - 将独立任务委托给子代理
   - 提供清晰的任务描述和上下文
   - 合理设置 `max_iters` 防止无限循环

---

## 错误处理

所有工具调用都可能返回错误，建议进行适当的错误处理：

```python
try:
    result = tool_registry.execute(call)
    if result.error:
        print(f"工具执行错误: {result.error}")
    else:
        print(f"结果: {result.content}")
except Exception as e:
    print(f"执行异常: {e}")
```

---

*文档生成时间：基于 src/yosuga/tools/ 目录下的源代码分析*
