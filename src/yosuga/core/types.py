from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional


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


PolicyAction = Literal["allow", "block", "ask_user"]


@dataclass
class ToolPolicyDecision:
    action: PolicyAction
    reason: str = ""
    suggestion: str = ""
    code: str = ""


@dataclass
class ModelResponse:
    text: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    reasoning_content: str = ""
