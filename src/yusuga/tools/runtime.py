import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List

from yusuga.core.types import ToolCall, ToolResult


ToolHandler = Callable[..., str]


class ToolRegistry:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self._handlers: Dict[str, ToolHandler] = {}
        self._descriptions: Dict[str, str] = {}
        self._input_schemas: Dict[str, Dict[str, Any]] = {}

    def register(
        self,
        name: str,
        description: str,
        handler: ToolHandler,
        input_schema: Dict[str, Any],
    ) -> None:
        self._handlers[name] = handler
        self._descriptions[name] = description
        self._input_schemas[name] = input_schema

    def execute(self, call: ToolCall) -> ToolResult:
        handler = self._handlers.get(call.name)
        if handler is None:
            return ToolResult(
                tool_use_id=call.id,
                ok=False,
                content="",
                error=f"Unknown tool: {call.name}",
                meta={"name": call.name},
            )

        try:
            output = handler(**call.input)
            return ToolResult(
                tool_use_id=call.id,
                ok=True,
                content=output,
                meta={"name": call.name},
            )
        except Exception as exc:
            return ToolResult(
                tool_use_id=call.id,
                ok=False,
                content="",
                error=str(exc),
                meta={"name": call.name},
            )

    def tool_specs(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": name,
                "description": self._descriptions[name],
                "input_schema": self._input_schemas[name],
            }
            for name in sorted(self._handlers.keys())
        ]

    def safe_path(self, p: str) -> Path:
        path = (self.root / p).resolve()
        if not str(path).startswith(str(self.root)):
            raise ValueError(f"Path escapes workspace: {p}")
        return path


def build_default_registry(root: Path) -> ToolRegistry:
    reg = ToolRegistry(root)

    reg.register(
        "echo",
        "Echo back text.",
        lambda text: text,
        {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    )

    def list_dir(path: str = ".") -> str:
        target = reg.safe_path(path)
        if not target.exists() or not target.is_dir():
            return f"Not a directory: {path}"
        names = sorted([p.name + ("/" if p.is_dir() else "") for p in target.iterdir()])
        return "\n".join(names) if names else "(empty directory)"

    def read_file(path: str, max_lines: int = 200) -> str:
        target = reg.safe_path(path)
        if not target.exists() or not target.is_file():
            return f"Not a file: {path}"
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        if len(lines) > max_lines:
            lines = lines[:max_lines] + [f"... ({len(lines) - max_lines} more lines)"]
        return "\n".join(lines) if lines else "(empty file)"

    def bash(command: str) -> str:
        blocked = [
            "del /s /q c:\\",
            "rd /s /q",
            "format",
            "shutdown",
            "reboot",
            "reg delete",
        ]
        lower = command.lower()
        if any(item in lower for item in blocked):
            return "Error: dangerous command blocked"

        proc = subprocess.run(
            command,
            shell=True,
            cwd=reg.root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = (proc.stdout + proc.stderr).strip()
        return output[:50000] if output else "(no output)"

    reg.register(
        "list_dir",
        "List entries in a directory.",
        list_dir,
        {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    )
    reg.register(
        "read_file",
        "Read a UTF-8 text file.",
        read_file,
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "max_lines": {"type": "integer", "minimum": 1},
            },
            "required": ["path"],
        },
    )
    reg.register(
        "bash",
        "Run a shell command in workspace.",
        bash,
        {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    )

    return reg
