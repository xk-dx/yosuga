import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from yosuga.core.types import ToolCall, ToolPolicyDecision


@dataclass
class PolicyRules:
    bash_blocked_substrings: List[str] = field(default_factory=list)
    bash_risky_substrings: List[str] = field(default_factory=list)
    read_file_max_lines_without_approval: int = 1000
    list_dir_root_like_paths: List[str] = field(default_factory=lambda: [".", "", "/", "\\"])
    audit_log_relative_path: str = ".yosuga/policy_audit.jsonl"
    session_log_relative_dir: str = ".yosuga/sessions"
    tool_max_retries: int = 2
    tool_backoff_base_seconds: float = 0.5
    tool_backoff_max_seconds: float = 4.0
    tool_backoff_jitter_seconds: float = 0.2
    tool_circuit_failure_threshold: int = 5
    tool_circuit_open_seconds: float = 30.0
    file_write_large_content_chars: int = 20000
    file_edit_large_change_chars: int = 20000


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        if path.exists() and path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {}


def load_policy_rules(project_root: Path) -> PolicyRules:
    config_path = project_root / "src" / "yosuga" / "config" / "policy_rules.json"
    data = _load_json(config_path)

    bash = data.get("bash", {}) if isinstance(data, dict) else {}
    read_file = data.get("read_file", {}) if isinstance(data, dict) else {}
    list_dir = data.get("list_dir", {}) if isinstance(data, dict) else {}
    audit = data.get("audit", {}) if isinstance(data, dict) else {}
    session = data.get("session", {}) if isinstance(data, dict) else {}
    resilience = data.get("resilience", {}) if isinstance(data, dict) else {}
    tool_resilience = resilience.get("tool", {}) if isinstance(resilience, dict) else {}
    file_ops = data.get("file_ops", {}) if isinstance(data, dict) else {}

    return PolicyRules(
        bash_blocked_substrings=[str(x).lower() for x in bash.get("blocked_substrings", [])],
        bash_risky_substrings=[str(x).lower() for x in bash.get("risky_substrings", [])],
        read_file_max_lines_without_approval=int(read_file.get("max_lines_without_approval", 1000)),
        list_dir_root_like_paths=[str(x) for x in list_dir.get("root_like_paths", [".", "", "/", "\\"])],
        audit_log_relative_path=str(audit.get("log_relative_path", ".yosuga/policy_audit.jsonl")),
        session_log_relative_dir=str(session.get("log_relative_dir", ".yosuga/sessions")),
        tool_max_retries=int(tool_resilience.get("max_retries", 2)),
        tool_backoff_base_seconds=float(tool_resilience.get("backoff_base_seconds", 0.5)),
        tool_backoff_max_seconds=float(tool_resilience.get("backoff_max_seconds", 4.0)),
        tool_backoff_jitter_seconds=float(tool_resilience.get("backoff_jitter_seconds", 0.2)),
        tool_circuit_failure_threshold=int(tool_resilience.get("circuit_failure_threshold", 5)),
        tool_circuit_open_seconds=float(tool_resilience.get("circuit_open_seconds", 30.0)),
        file_write_large_content_chars=int(file_ops.get("write_large_content_chars", 20000)),
        file_edit_large_change_chars=int(file_ops.get("edit_large_change_chars", 20000)),
    )


class PolicyAuditLogger:
    def __init__(self, workspace_root: Path, relative_path: str):
        self._path = (workspace_root / relative_path).resolve()
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def log(
        self,
        *,
        call: ToolCall,
        decision: ToolPolicyDecision,
        outcome: str,
        approved: Optional[bool] = None,
        error: str = "",
    ) -> None:
        event = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "tool_use_id": call.id,
            "tool_name": call.name,
            "tool_input": call.input,
            "policy_action": decision.action,
            "policy_code": decision.code,
            "policy_reason": decision.reason,
            "policy_suggestion": decision.suggestion,
            "outcome": outcome,
            "approved": approved,
            "error": error,
        }
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
