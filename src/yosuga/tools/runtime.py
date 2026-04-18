import subprocess
import os
import json
import random
import time
import difflib
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from yosuga.config.policy import PolicyAuditLogger, PolicyRules, load_policy_rules
from yosuga.config.skills import SkillCatalog
from yosuga.core.types import ToolCall, ToolPolicyDecision, ToolResult
from yosuga.tools.policy import ToolPolicyEngine


ToolHandler = Callable[..., Any]
ApprovalHandler = Callable[[ToolCall, ToolPolicyDecision], str]
EventHandler = Callable[[str], None]


class ToolRegistry:
    def __init__(
        self,
        root: Path,
        policy_rules: Optional[PolicyRules] = None,
        policy_audit_logger: Optional[PolicyAuditLogger] = None,
    ):
        self.root = root.resolve()
        project_root = Path(os.getenv("yosuga_PROJECT_ROOT", str(self.root))).resolve()
        self.project_root = project_root
        self.policy_rules = policy_rules or load_policy_rules(project_root)
        self.skill_catalog = SkillCatalog(workspace_root=self.root, project_root=project_root)
        self.policy_audit_logger = policy_audit_logger or PolicyAuditLogger(
            workspace_root=self.root,
            relative_path=self.policy_rules.audit_log_relative_path,
        )
        self._policy_engine = ToolPolicyEngine(workspace_root=self.root, rules=self.policy_rules)
        self._handlers: Dict[str, ToolHandler] = {}
        self._descriptions: Dict[str, str] = {}
        self._input_schemas: Dict[str, Dict[str, Any]] = {}
        self._last_call_fingerprint: Optional[str] = None
        self._tool_fail_streak: Dict[str, int] = {}
        self._tool_circuit_open_until: Dict[str, float] = {}

    def set_mutation_mode(self, mode: str) -> None:
        self._policy_engine.set_mutation_mode(mode)

    def get_mutation_mode(self) -> str:
        return self._policy_engine.get_mutation_mode()

    def _audit(
        self,
        *,
        call: ToolCall,
        decision: ToolPolicyDecision,
        outcome: str,
        approved: Optional[bool] = None,
        error: str = "",
    ) -> None:
        try:
            self.policy_audit_logger.log(
                call=call,
                decision=decision,
                outcome=outcome,
                approved=approved,
                error=error,
            )
        except Exception:
            pass

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

    def _fingerprint_call(self, call: ToolCall) -> str:
        try:
            payload = json.dumps(call.input, sort_keys=True, ensure_ascii=True, default=str)
        except Exception:
            payload = repr(call.input)
        return f"{call.name}::{payload}"

    def _is_circuit_open(self, tool_name: str) -> bool:
        open_until = self._tool_circuit_open_until.get(tool_name, 0.0)
        return time.time() < open_until

    def _mark_tool_success(self, tool_name: str) -> None:
        self._tool_fail_streak[tool_name] = 0
        self._tool_circuit_open_until.pop(tool_name, None)

    def _mark_tool_failure(self, tool_name: str) -> None:
        streak = self._tool_fail_streak.get(tool_name, 0) + 1
        self._tool_fail_streak[tool_name] = streak
        if streak >= self.policy_rules.tool_circuit_failure_threshold:
            self._tool_circuit_open_until[tool_name] = time.time() + self.policy_rules.tool_circuit_open_seconds

    def _is_retryable_tool_error(self, exc: Exception) -> bool:
        retryable_types = (
            TimeoutError,
            ConnectionError,
            OSError,
            subprocess.TimeoutExpired,
        )
        if isinstance(exc, retryable_types):
            return True
        msg = str(exc).lower()
        retryable_msg_tokens = [
            "timeout",
            "temporarily unavailable",
            "connection reset",
            "connection aborted",
            "connection refused",
            "network",
        ]
        return any(token in msg for token in retryable_msg_tokens)

    def _backoff_delay(self, attempt: int) -> float:
        base = max(0.0, self.policy_rules.tool_backoff_base_seconds)
        cap = max(base, self.policy_rules.tool_backoff_max_seconds)
        jitter = max(0.0, self.policy_rules.tool_backoff_jitter_seconds)
        delay = min(cap, base * (2 ** max(0, attempt - 1)))
        return delay + random.uniform(0.0, jitter)

    def _policy_for(self, call: ToolCall) -> ToolPolicyDecision:
        return self._policy_engine.decide(call)

    def _build_event_preview(self, call: ToolCall) -> str:
        if call.name == "write_file":
            path = str(call.input.get("path", ""))
            content = str(call.input.get("content", ""))
            overwrite = bool(call.input.get("overwrite", False))
            target = self.safe_path(path)

            if target.exists() and not overwrite:
                return "Target file already exists and overwrite is disabled."

            existed_before = target.exists()
            before_text = target.read_text(encoding="utf-8", errors="replace") if existed_before else ""
            from_label = f"a/{path}" if existed_before else "/dev/null"
            to_label = f"b/{path}"
            diff_lines = list(
                difflib.unified_diff(
                    before_text.splitlines(keepends=True),
                    content.splitlines(keepends=True),
                    fromfile=from_label,
                    tofile=to_label,
                    lineterm="",
                )
            )
            diff_text = "\n".join(diff_lines).strip() or "(no diff)"
            summary = f"Wrote {len(content)} characters to {target.name}"
            return f"{summary}\n\n[diff]\n{diff_text}"

        if call.name == "edit_file":
            path = str(call.input.get("path", ""))
            old_text = str(call.input.get("old_text", ""))
            new_text = str(call.input.get("new_text", ""))
            replace_all = bool(call.input.get("replace_all", False))
            target = self.safe_path(path)

            if not target.exists() or not target.is_file():
                return f"Not a file: {path}"

            original = target.read_text(encoding="utf-8", errors="replace")
            if old_text not in original:
                return "Old text not found in file"

            if replace_all:
                updated = original.replace(old_text, new_text)
                replaced_count = original.count(old_text)
            else:
                updated = original.replace(old_text, new_text, 1)
                replaced_count = 1

            diff_lines = list(
                difflib.unified_diff(
                    original.splitlines(keepends=True),
                    updated.splitlines(keepends=True),
                    fromfile=f"a/{path}",
                    tofile=f"b/{path}",
                    lineterm="",
                )
            )
            diff_text = "\n".join(diff_lines).strip() or "(no diff)"
            summary = f"Replaced {replaced_count} occurrence(s) in {target.name}"
            return f"{summary}\n\n[diff]\n{diff_text}"

        return ""

    def execute(
        self,
        call: ToolCall,
        approve: Optional[ApprovalHandler] = None,
        on_event: Optional[EventHandler] = None,
    ) -> ToolResult:
        fingerprint = self._fingerprint_call(call)

        if self._last_call_fingerprint == fingerprint:
            duplicate_decision = ToolPolicyDecision(
                action="block",
                code="duplicate_immediate_call",
                reason="Same tool with identical arguments was requested immediately again.",
                suggestion="Avoid immediate duplicate calls. Adjust parameters or ask the model to reason from the previous result.",
            )
            self._audit(call=call, decision=duplicate_decision, outcome="blocked_duplicate_immediate")
            return ToolResult(
                tool_use_id=call.id,
                ok=False,
                content="",
                error="Policy blocked immediate duplicate tool call.",
                meta={
                    "name": call.name,
                    "policy_action": duplicate_decision.action,
                    "policy_code": duplicate_decision.code,
                    "policy_reason": duplicate_decision.reason,
                    "policy_suggestion": duplicate_decision.suggestion,
                },
            )

        self._last_call_fingerprint = fingerprint
        decision = self._policy_for(call)

        if decision.action == "block":
            self._audit(call=call, decision=decision, outcome="blocked")
            return ToolResult(
                tool_use_id=call.id,
                ok=False,
                content="",
                error="Policy blocked this tool call.",
                meta={
                    "name": call.name,
                    "policy_action": decision.action,
                    "policy_code": decision.code,
                    "policy_reason": decision.reason,
                    "policy_suggestion": decision.suggestion,
                },
            )

        if decision.action == "ask_user":
            if on_event and call.name in {"write_file", "edit_file"}:
                preview_text = self._build_event_preview(call)
                if preview_text:
                    on_event(f"[tool] preview {call.name}\n{preview_text}")
            approval_message = approve(call, decision) if approve is not None else "Tool call was not approved."
            if approval_message:
                self._audit(call=call, decision=decision, outcome="approval_denied", approved=False)
                error_text = f"user rejected your approval: {approval_message}".strip()
                return ToolResult(
                    tool_use_id=call.id,
                    ok=False,
                    content="",
                    error=error_text,
                    meta={
                        "name": call.name,
                        "policy_action": decision.action,
                        "policy_code": decision.code,
                        "policy_reason": decision.reason,
                        "policy_suggestion": decision.suggestion,
                    },
                )
            self._audit(call=call, decision=decision, outcome="approved", approved=True)

        handler = self._handlers.get(call.name)
        if handler is None:
            self._audit(call=call, decision=decision, outcome="unknown_tool", error=f"Unknown tool: {call.name}")
            return ToolResult(
                tool_use_id=call.id,
                ok=False,
                content="",
                error=f"Unknown tool: {call.name}",
                meta={"name": call.name},
            )

        if self._is_circuit_open(call.name):
            open_until = self._tool_circuit_open_until.get(call.name, time.time())
            wait_seconds = max(0.0, open_until - time.time())
            circuit_decision = ToolPolicyDecision(
                action="block",
                code="tool_circuit_open",
                reason="Tool is temporarily unavailable due to repeated failures.",
                suggestion=f"Wait about {wait_seconds:.1f}s before retrying this tool, or use an alternative tool.",
            )
            self._audit(call=call, decision=circuit_decision, outcome="blocked_circuit_open")
            return ToolResult(
                tool_use_id=call.id,
                ok=False,
                content="",
                error="Tool circuit is open.",
                meta={
                    "name": call.name,
                    "policy_action": circuit_decision.action,
                    "policy_code": circuit_decision.code,
                    "policy_reason": circuit_decision.reason,
                    "policy_suggestion": circuit_decision.suggestion,
                    "circuit_open_until": open_until,
                },
            )

        max_attempts = max(1, self.policy_rules.tool_max_retries + 1)
        last_exc: Optional[Exception] = None
        for attempt in range(1, max_attempts + 1):
            try:
                output = handler(**call.input)
                self._mark_tool_success(call.name)
                self._audit(call=call, decision=decision, outcome="executed")
                meta = {
                    "name": call.name,
                    "policy_action": decision.action,
                    "circuit_state": "closed",
                }
                if attempt > 1:
                    meta["retry_count"] = attempt - 1
                return ToolResult(
                    tool_use_id=call.id,
                    ok=True,
                    content=str(output),
                    meta=meta,
                )
            except Exception as exc:
                last_exc = exc
                retryable = self._is_retryable_tool_error(exc)
                self._mark_tool_failure(call.name)
                streak = self._tool_fail_streak.get(call.name, 0)

                if streak >= self.policy_rules.tool_circuit_failure_threshold:
                    self._audit(call=call, decision=decision, outcome="tool_circuit_opened", error=str(exc))

                if attempt >= max_attempts or not retryable:
                    self._audit(call=call, decision=decision, outcome="tool_error", error=str(exc))
                    circuit_state = "open" if self._is_circuit_open(call.name) else "closed"
                    meta = {
                        "name": call.name,
                        "policy_action": decision.action,
                        "circuit_state": circuit_state,
                    }
                    if retryable:
                        meta["retryable"] = True
                    if attempt > 1:
                        meta["retry_count"] = attempt - 1
                    return ToolResult(
                        tool_use_id=call.id,
                        ok=False,
                        content="",
                        error=str(exc),
                        meta=meta,
                    )

                delay = self._backoff_delay(attempt)
                self._audit(
                    call=call,
                    decision=decision,
                    outcome="tool_retry_scheduled",
                    error=f"attempt={attempt}; delay_seconds={delay:.3f}; error={exc}",
                )
                time.sleep(delay)

        self._audit(call=call, decision=decision, outcome="tool_error", error=str(last_exc) if last_exc else "unknown")
        return ToolResult(
            tool_use_id=call.id,
            ok=False,
            content="",
            error=str(last_exc) if last_exc else "Unknown tool execution error",
            meta={"name": call.name, "policy_action": decision.action},
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

    def write_file(path: str, content: str, overwrite: bool = False) -> str:
        target = reg.safe_path(path)
        if target.exists() and not overwrite:
            return "Target file already exists and overwrite is disabled."
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        summary = f"Wrote {len(content)} characters to {target.name}"
        return summary

    def edit_file(path: str, old_text: str, new_text: str, replace_all: bool = False) -> str:
        target = reg.safe_path(path)
        original = target.read_text(encoding="utf-8", errors="replace")
        if old_text not in original:
            return "Old text not found in file"
        if replace_all:
            updated = original.replace(old_text, new_text)
            replaced_count = original.count(old_text)
        else:
            updated = original.replace(old_text, new_text, 1)
            replaced_count = 1
        target.write_text(updated, encoding="utf-8")
        summary = f"Replaced {replaced_count} occurrence(s) in {target.name}"
        return summary

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
        proc = subprocess.run(
            command,
            shell=True,
            cwd=reg.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        output = (stdout + stderr).strip()
        if output:
            if proc.returncode != 0:
                output = f"[exit_code={proc.returncode}]\n{output}"
            return output[:50000]
        if proc.returncode != 0:
            return f"[exit_code={proc.returncode}] (no output)"
        return "(no output)"

    def list_skills(scope: str = "all") -> str:
        scope_norm = (scope or "all").strip().lower()
        metas = reg.skill_catalog.list_meta()
        if not metas:
            return "(no skills found)"

        lines: List[str] = []
        for meta in metas:
            if scope_norm == "workspace" and not str(meta.root_dir).startswith(str(reg.root)):
                continue
            desc = meta.description.strip().replace("\n", " ")
            lines.append(f"{meta.slug} | {meta.name} | {desc}")

        return "\n".join(lines) if lines else "(no skills found for scope)"

    def use_skill(skill: str, max_chars: int = 50000) -> str:
        meta, content, scripts = reg.skill_catalog.load_full(skill=skill, max_chars=max_chars)
        script_block = "\n".join(f"- {s}" for s in scripts) if scripts else "- (none)"
        return (
            f"[skill]\n"
            f"slug: {meta.slug}\n"
            f"name: {meta.name}\n"
            f"root: {meta.root_dir}\n"
            f"scripts:\n{script_block}\n\n"
            f"[SKILL.md]\n{content}"
        )

    def glob(
        pattern: str = "**/*",
        path: str = ".",
        max_results: int = 500,
        include_dirs: bool = False,
    ) -> str:
        effective_pattern = (pattern or "**/*").strip() or "**/*"
        effective_path = (path or ".").strip() or "."
        limit = max(1, min(int(max_results or 500), 5000))

        target = reg.safe_path(effective_path)
        if not target.exists() or not target.is_dir():
            return f"Not a directory: {effective_path}"

        matches: List[str] = []
        for p in sorted(target.glob(effective_pattern)):
            if p.is_dir() and not include_dirs:
                continue
            rel = p.relative_to(reg.root).as_posix()
            if p.is_dir():
                rel += "/"
            matches.append(rel)
            if len(matches) >= limit:
                break

        if not matches:
            return "(no matches)"
        return "\n".join(matches)

    def grep(
        query: str = "",
        path: str = ".",
        is_regexp: bool = False,
        max_results: int = 200,
        case_sensitive: bool = False,
    ) -> str:
        effective_query = (query or "").strip()
        if not effective_query:
            return "Query is required."

        effective_path = (path or ".").strip() or "."
        effective_is_regexp = bool(is_regexp)
        limit = max(1, min(int(max_results or 200), 5000))

        target = reg.safe_path(effective_path)
        if not target.exists():
            return f"Not found: {effective_path}"

        flags = 0 if case_sensitive else re.IGNORECASE
        regex = None
        if effective_is_regexp:
            try:
                regex = re.compile(effective_query, flags)
            except re.error as exc:
                return f"Invalid regex: {exc}"

        def _iter_files() -> List[Path]:
            if target.is_file():
                return [target]
            files: List[Path] = []
            for p in target.rglob("*"):
                if p.is_file():
                    files.append(p)
            return files

        def _is_binary(file_path: Path) -> bool:
            try:
                chunk = file_path.read_bytes()[:4096]
            except Exception:
                return True
            return b"\x00" in chunk

        lines_out: List[str] = []
        for file_path in _iter_files():
            if _is_binary(file_path):
                continue
            try:
                with file_path.open("r", encoding="utf-8", errors="replace") as f:
                    for idx, line in enumerate(f, start=1):
                        text = line.rstrip("\n\r")
                        matched = False
                        if regex is not None:
                            matched = bool(regex.search(text))
                        else:
                            if case_sensitive:
                                matched = effective_query in text
                            else:
                                matched = effective_query.lower() in text.lower()
                        if matched:
                            rel = file_path.relative_to(reg.root).as_posix()
                            lines_out.append(f"{rel}:{idx}:{text}")
                            if len(lines_out) >= limit:
                                return "\n".join(lines_out)
            except Exception:
                continue

        return "\n".join(lines_out) if lines_out else "(no matches)"

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
        "glob",
        "Find files by glob pattern in the workspace.",
        glob,
        {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string"},
                "max_results": {"type": "integer", "minimum": 1},
                "include_dirs": {"type": "boolean"},
            },
        },
    )
    reg.register(
        "grep",
        "Search text in files under a path.",
        grep,
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "path": {"type": "string"},
                "is_regexp": {"type": "boolean"},
                "max_results": {"type": "integer", "minimum": 1},
                "case_sensitive": {"type": "boolean"},
            },
            "required": ["query"],
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
        "list_skills",
        "List available skills from .yosuga/skills metadata index.",
        list_skills,
        {
            "type": "object",
            "properties": {
                "scope": {"type": "string", "enum": ["all", "workspace"]},
            },
        },
    )
    reg.register(
        "use_skill",
        "Load full SKILL.md and scripts list for one skill by slug or name.",
        use_skill,
        {
            "type": "object",
            "properties": {
                "skill": {"type": "string"},
                "max_chars": {"type": "integer", "minimum": 1000, "maximum": 200000},
            },
            "required": ["skill"],
        },
    )
    reg.register(
        "write_file",
        "Write UTF-8 text to a file in the workspace.",
        write_file,
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "overwrite": {"type": "boolean"},
            },
            "required": ["path", "content"],
        },
    )
    reg.register(
        "edit_file",
        "Edit a UTF-8 text file by replacing text in the workspace.",
        edit_file,
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_text": {"type": "string"},
                "new_text": {"type": "string"},
                "replace_all": {"type": "boolean"},
            },
            "required": ["path", "old_text", "new_text"],
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
