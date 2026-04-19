"""Three-tier history compression for managing context window overflow."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional
from dataclasses import dataclass


@dataclass
class CompactorConfig:
    """Configuration for compression thresholds."""
    micro_threshold_chars: int = 3000
    micro_min_release_ratio: float = 0.2
    auto_token_threshold: float = 0.90
    auto_keep_recent_turns: int = 3
    full_context_window: int = 20000


class MicroCompactor:
    """First layer: Remove redundant tool outputs from history."""

    def __init__(self, config: Optional[CompactorConfig] = None):
        self.config = config or CompactorConfig()
        self.archived_cache: Dict[str, str] = {}  # tool_use_id -> original_content

    def compact_history(self, history: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], int]:
        """
        Scan history for large tool results that have been processed (not referenced).
        Replace with placeholders.

        Returns:
            (compacted_history, chars_released)
        """
        if not history:
            return history, 0

        compacted = []
        chars_released = 0
        keep_recent = max(0, int(self.config.auto_keep_recent_turns))
        recent_start_idx = max(0, len(history) - keep_recent)

        for idx, msg in enumerate(history):
            # Keep the most recent messages untouched to avoid compacting active context.
            if idx >= recent_start_idx:
                compacted.append(msg)
                continue

            if msg.get("role") != "user" or not isinstance(msg.get("content"), list):
                compacted.append(msg)
                continue

            # Message contains tool_result blocks
            new_content = []
            for item in msg.get("content", []):
                if item.get("type") == "tool_result":
                    content = item.get("content", "")
                    if isinstance(content, str) and len(content) > self.config.micro_threshold_chars:
                        # Check if this result is referenced in later messages
                        tool_use_id = item.get("tool_use_id", "")
                        if not self._is_referenced_later(history, idx, tool_use_id):
                            # Replace with placeholder
                            placeholder = {
                                **item,
                                "content": f"[ARCHIVED: {len(content)} chars, tool={item.get('name')}]",
                            }
                            new_content.append(placeholder)
                            self.archived_cache[tool_use_id] = content
                            chars_released += len(content)
                            continue

                new_content.append(item)

            compacted.append({"role": msg["role"], "content": new_content})

        return compacted, chars_released

    def _is_referenced_later(self, history: List[Dict], current_idx: int, tool_use_id: str) -> bool:
        """Check if a tool result is referenced in subsequent messages."""
        for msg in history[current_idx + 1 :]:
            content = msg.get("content", "")
            if isinstance(content, str):
                # Simple heuristic: check if tool_use_id appears in text
                if tool_use_id in content:
                    return True
        return False

    def restore_archived(self, tool_use_id: str) -> Optional[str]:
        """Restore archived content if needed (for offline analysis)."""
        return self.archived_cache.get(tool_use_id)


class AutoCompactor:
    """Second layer: LLM-driven structured summarization at token threshold."""

    def __init__(self, model: Any, config: Optional[CompactorConfig] = None):
        self.model = model
        self.config = config or CompactorConfig()

    def should_compact(self, usage: Optional[Dict[str, int]]) -> bool:
        """Check if token usage exceeds threshold."""
        if not usage:
            return False
        prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
        completion_tokens = int(usage.get("completion_tokens", 0) or 0)
        total = prompt_tokens + completion_tokens
        ratio = total / self.config.full_context_window
        return ratio >= self.config.auto_token_threshold

    def compact_history(self, history: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], int]:
        """
        Generate structured summary of middle turns, keep recent turns intact.

        Returns:
            (compacted_history, estimated_tokens_saved)
        """
        if len(history) <= self.config.auto_keep_recent_turns * 2:
            return history, 0

        # Extract turns to summarize
        num_to_summarize = len(history) - self.config.auto_keep_recent_turns
        middle_turns = history[:num_to_summarize]
        recent_turns = history[num_to_summarize:]

        # Build summarization prompt
        summary_prompt = self._build_summary_prompt(middle_turns)

        # Call model to summarize
        try:
            summary_response = self.model.respond(
                [{"role": "user", "content": summary_prompt}],
                tool_specs=[],
            )
            summary_text = (summary_response.text or "").strip()
            if not summary_text:
                return history, 0
        except Exception:
            # If summarization fails, return unchanged
            return history, 0

        # Create summary block
        summary_block = {
            "role": "user",
            "content": [
                {
                    "type": "summary",
                    "from_turn": 1,
                    "to_turn": num_to_summarize,
                    "content": summary_text,
                    "token_estimate": len(summary_text) // 4,  # rough estimate
                }
            ],
        }

        # Reconstruct history
        compacted = [summary_block] + recent_turns
        estimated_saved = sum(len(json.dumps(msg)) for msg in middle_turns) - len(
            json.dumps(summary_block)
        )

        return compacted, estimated_saved

    def _build_summary_prompt(self, turns: List[Dict[str, Any]]) -> str:
        """Build prompt for LLM summarization."""
        return (
            "Summarize the agent's work and decisions in the following interaction history. "
            "Focus on key decisions, findings, files touched, and next steps. "
            "Output as JSON with keys: decisions, findings, files_touched, current_state.\n\n"
            + json.dumps(turns, ensure_ascii=False, default=str)
        )


class FullCompactor:
    """Third layer: Archive full history and reset to lightweight context."""

    def __init__(self, session_logger: Any):
        self.session_logger = session_logger

    def archive_and_reset(
        self, history: List[Dict[str, Any]], current_turn: int, user_input: str
    ) -> List[Dict[str, Any]]:
        """
        Archive complete history and reset with lightweight context.

        Returns:
            new_history (system prompt + restored context)
        """
        # 1. Log archive event
        if self.session_logger:
            try:
                self.session_logger.log(
                    "archive_history",
                    {
                        "turn": current_turn,
                        "history_length": len(history),
                    },
                )
            except Exception:
                pass

        # 2. Extract key information
        key_info = self._extract_key_info(history)

        # 3. Build lightweight history
        new_history = self._build_lightweight_history(user_input, key_info)

        return new_history

    def _extract_key_info(self, history: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Extract critical information from full history."""
        files_touched = set()
        tool_use_paths: Dict[str, str] = {}
        decisions = []
        tool_errors: List[str] = []
        user_instructions: List[str] = []
        current_state = ""
        tool_result_count = 0

        for msg in history:
            content = msg.get("content", "")
            if isinstance(content, list):
                for item in content:
                    if item.get("type") == "tool_use":
                        # Reliable source: assistant tool_use contains original input args.
                        tool_use_id = str(item.get("id", "")).strip()
                        input_obj = item.get("input", {})
                        if isinstance(input_obj, dict):
                            path = str(input_obj.get("path", "")).strip()
                            if tool_use_id and path:
                                tool_use_paths[tool_use_id] = path

                    if item.get("type") == "tool_result":
                        tool_result_count += 1
                        name = str(item.get("name", "")).strip()
                        if name:
                            decisions.append(f"tool:{name}")

                        err = str(item.get("error", "") ).strip()
                        if err:
                            tool_errors.append(err)

                        # Prefer path mapped from tool_use by id.
                        tool_use_id = str(item.get("tool_use_id", "")).strip()
                        mapped_path = tool_use_paths.get(tool_use_id, "")
                        if mapped_path:
                            files_touched.add(mapped_path)

                        # Best-effort extraction from tool content.
                        item_content = str(item.get("content", ""))
                        for p in self._extract_paths_from_text(item_content):
                            files_touched.add(p)
            elif isinstance(content, str):
                if msg.get("role") == "user" and len(content) > 0:
                    # Keep recent user intent/constraints for recovery context.
                    user_instructions.append(content[:200])
                # Last assistant message is current state
                if msg.get("role") == "assistant" and len(content) > 0:
                    current_state = content[:500]  # Keep first 500 chars
                    decisions.append(content[:120])

        return {
            "files_touched": list(files_touched)[:20],
            "decisions": decisions[-10:],
            "tool_errors": tool_errors[-5:],
            "user_instructions": user_instructions[-10:],
            "current_state": current_state,
            "history_length": len(history),
            "tool_result_count": tool_result_count,
        }

    def _build_lightweight_history(
        self, user_input: str, key_info: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Build new history with restored context."""
        files = key_info.get("files_touched", [])
        decisions = key_info.get("decisions", [])
        tool_errors = key_info.get("tool_errors", [])
        user_instructions = key_info.get("user_instructions", [])
        compact_state = {
            "history_length": key_info.get("history_length", 0),
            "tool_result_count": key_info.get("tool_result_count", 0),
            "files_touched": files,
            "recent_decisions": decisions,
            "recent_tool_errors": tool_errors,
            "recent_user_instructions": user_instructions,
            "current_state": key_info.get("current_state", ""),
        }

        context_msg = (
            f"[CONTEXT RESTORED FROM ARCHIVE]\n\n"
            f"Original task: {user_input}\n\n"
            f"Previous work (structured):\n"
            f"{json.dumps(compact_state, ensure_ascii=False)}\n\n"
            f"Continue from where you left off."
        )

        return [
            {
                "role": "user",
                "content": context_msg,
            }
        ]

    @staticmethod
    def _extract_paths_from_text(text: str) -> List[str]:
        """Best-effort path extraction from tool outputs."""
        if not text:
            return []

        # Matches common path-like tokens with extensions, e.g. src/app.py, a/b/c.ts
        path_pattern = re.compile(r"(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\.[A-Za-z0-9_.-]+")
        found = path_pattern.findall(text)
        # Deduplicate while preserving order.
        seen = set()
        ordered: List[str] = []
        for p in found:
            if p not in seen:
                seen.add(p)
                ordered.append(p)
        return ordered[:20]
