from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from yosuga.config.policy import PolicyRules
from yosuga.core.types import ToolCall, ToolPolicyDecision


@dataclass
class ToolPolicyEngine:
    workspace_root: Path
    rules: PolicyRules

    def _safe_path(self, path: str) -> Path:
        target = (self.workspace_root / path).resolve()
        if not str(target).startswith(str(self.workspace_root)):
            raise ValueError("Path escapes workspace root")
        return target

    def decide(self, call: ToolCall) -> ToolPolicyDecision:
        if call.name in {"write_file", "edit_file"}:
            return self._decide_file_ops(call)

        if call.name == "bash":
            return self._decide_bash(call)

        if call.name == "read_file":
            max_lines = int(call.input.get("max_lines", 200) or 200)
            if max_lines > self.rules.read_file_max_lines_without_approval:
                return ToolPolicyDecision(
                    action="ask_user",
                    code="large_read",
                    reason="Requested file read is very large.",
                    suggestion="Reduce max_lines or read a specific range first.",
                )
            return ToolPolicyDecision(action="allow")

        if call.name == "list_dir":
            path = str(call.input.get("path", ""))
            if path in self.rules.list_dir_root_like_paths:
                return ToolPolicyDecision(
                    action="ask_user",
                    code="broad_listing",
                    reason="Listing the root may produce noisy output.",
                    suggestion="Confirm root listing or narrow path to a subdirectory.",
                )
            return ToolPolicyDecision(action="allow")

        return ToolPolicyDecision(action="allow")

    def _decide_bash(self, call: ToolCall) -> ToolPolicyDecision:
        command = str(call.input.get("command", ""))
        lower = command.lower()

        if any(item in lower for item in self.rules.bash_blocked_substrings):
            return ToolPolicyDecision(
                action="block",
                code="destructive_command",
                reason="Command contains dangerous destructive operation.",
                suggestion="Use non-destructive inspection commands first, for example: dir, type, rg, git status.",
            )

        if any(token in lower for token in self.rules.bash_risky_substrings):
            return ToolPolicyDecision(
                action="ask_user",
                code="risky_command",
                reason="Command may modify or delete important files.",
                suggestion="Confirm intent and scope, and prefer a dry-run command if available.",
            )

        return ToolPolicyDecision(action="allow")

    def _decide_file_ops(self, call: ToolCall) -> ToolPolicyDecision:
        path = str(call.input.get("path", ""))
        if not path:
            return ToolPolicyDecision(
                action="block",
                code="missing_path",
                reason="Target path is required.",
                suggestion="Provide a workspace-relative path.",
            )

        try:
            target = self._safe_path(path)
        except Exception:
            return ToolPolicyDecision(
                action="block",
                code="path_escape",
                reason="Target path escapes the workspace root.",
                suggestion="Use a path inside the workspace root.",
            )

        if call.name == "write_file":
            return self._decide_write_file(call, target)

        return self._decide_edit_file(call, target)

    def _decide_write_file(self, call: ToolCall, target: Path) -> ToolPolicyDecision:
        content = str(call.input.get("content", ""))
        overwrite = bool(call.input.get("overwrite", False))
        target_exists = target.exists()

        if len(content) > self.rules.file_write_large_content_chars:
            return ToolPolicyDecision(
                action="ask_user",
                code="large_write",
                reason="Write content is large.",
                suggestion="Confirm the write or split it into smaller chunks.",
            )

        if target_exists and not overwrite:
            return ToolPolicyDecision(
                action="block",
                code="file_exists",
                reason="Target file already exists and overwrite is disabled.",
                suggestion="Set overwrite=true if you intend to replace the file.",
            )

        if target_exists and overwrite:
            return ToolPolicyDecision(
                action="ask_user",
                code="overwrite_existing_file",
                reason="Writing will replace an existing file.",
                suggestion="Confirm the overwrite before proceeding.",
            )

        return ToolPolicyDecision(action="allow")

    def _decide_edit_file(self, call: ToolCall, target: Path) -> ToolPolicyDecision:
        old_text = str(call.input.get("old_text", ""))
        new_text = str(call.input.get("new_text", ""))
        replace_all = bool(call.input.get("replace_all", False))
        target_exists = target.exists()

        if not target_exists:
            return ToolPolicyDecision(
                action="block",
                code="file_missing",
                reason="Target file does not exist.",
                suggestion="Create the file first with write_file.",
            )

        if len(old_text) == 0:
            return ToolPolicyDecision(
                action="block",
                code="empty_search_text",
                reason="edit_file requires a non-empty old_text to avoid blind replacement.",
                suggestion="Provide the exact text to replace.",
            )

        if len(old_text) + len(new_text) > self.rules.file_edit_large_change_chars or replace_all:
            return ToolPolicyDecision(
                action="ask_user",
                code="large_edit",
                reason="Edit change is large or replace_all is enabled.",
                suggestion="Confirm the edit or narrow the replacement scope.",
            )

        return ToolPolicyDecision(action="allow")