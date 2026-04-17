from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ToolCall:
    id: str
    name: str
    input: Dict[str, Any]


@dataclass
class ToolResult:
    tool_use_id: str
    ok: bool
    content: str
    error: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelResponse:
    text: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    reasoning_content: str = ""
