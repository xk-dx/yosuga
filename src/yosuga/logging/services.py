from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from yosuga.core.types import ToolCall, ToolResult


@dataclass
class LogCompactConfig:
    max_string_chars: int = 200
    max_list_items: int = 50
    max_dict_items: int = 100
    max_request_messages: int = 12
    max_tool_specs: int = 20


class LogCompactionService:
    def __init__(self, config: LogCompactConfig | None = None):
        self.config = config or LogCompactConfig()

    def compact_value(self, value: Any) -> Any:
        if isinstance(value, str):
            if len(value) <= self.config.max_string_chars:
                return value
            omitted = len(value) - self.config.max_string_chars
            return value[: self.config.max_string_chars] + f"... [truncated {omitted} chars]"

        if isinstance(value, list):
            head = [self.compact_value(v) for v in value[: self.config.max_list_items]]
            if len(value) > self.config.max_list_items:
                head.append(f"... [truncated {len(value) - self.config.max_list_items} items]")
            return head

        if isinstance(value, dict):
            compacted: Dict[str, Any] = {}
            items = list(value.items())
            for k, v in items[: self.config.max_dict_items]:
                compacted[str(k)] = self.compact_value(v)
            if len(items) > self.config.max_dict_items:
                compacted["__truncated_keys__"] = len(items) - self.config.max_dict_items
            return compacted

        return value


class LogPayloadService:
    def __init__(self, compactor: LogCompactionService):
        self.compactor = compactor

    def model_request_payload(
        self,
        *,
        turn_id: int,
        phase: str,
        request_messages: List[Dict[str, Any]],
        tool_specs: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return {
            "turn_id": turn_id,
            "phase": phase,
            "request_messages_count": len(request_messages),
            "request_messages_preview": self._compact_request_messages(request_messages),
            "tool_specs_count": len(tool_specs),
            "tool_specs_preview": self._compact_tool_specs(tool_specs),
        }

    def model_response_payload(
        self,
        *,
        turn_id: int,
        text: str,
        reasoning_content: str,
        tool_calls_count: int,
        usage: Dict[str, Any],
        tool_validation_errors: List[str],
    ) -> Dict[str, Any]:
        return {
            "turn_id": turn_id,
            "text": self.compactor.compact_value(text),
            "reasoning_content": self.compactor.compact_value(reasoning_content),
            "tool_calls_count": int(tool_calls_count),
            "usage": self.compactor.compact_value(usage),
            "tool_validation_errors": self.compactor.compact_value(tool_validation_errors),
        }

    def tool_call_payload(self, *, turn_id: int, call: ToolCall) -> Dict[str, Any]:
        return {
            "turn_id": turn_id,
            "tool_use_id": call.id,
            "name": call.name,
            "input": self.compactor.compact_value(call.input),
        }

    def tool_result_payload(
        self,
        *,
        turn_id: int,
        call_name: str,
        result: ToolResult,
        content_preview: str,
    ) -> Dict[str, Any]:
        return {
            "turn_id": turn_id,
            "tool_use_id": result.tool_use_id,
            "name": result.meta.get("name", call_name),
            "ok": result.ok,
            "error": self.compactor.compact_value(result.error),
            "meta": self.compactor.compact_value(result.meta),
            "content_preview": self.compactor.compact_value(content_preview),
        }

    def turn_user_input_payload(self, *, turn_id: int, text: str) -> Dict[str, Any]:
        return {
            "turn_id": turn_id,
            "text": self.compactor.compact_value(text),
        }

    def turn_complete_payload(self, *, turn_id: int, answer: str) -> Dict[str, Any]:
        return {
            "turn_id": turn_id,
            "answer": self.compactor.compact_value(answer),
        }

    def history_compact_payload(self, *, turn_id: int, reason_or_saved: Any, field: str) -> Dict[str, Any]:
        return {
            "turn_id": turn_id,
            field: self.compactor.compact_value(reason_or_saved),
        }

    def _compact_request_messages(self, request_messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        preview: List[Dict[str, Any]] = []
        max_count = self.compactor.config.max_request_messages
        for idx, msg in enumerate(request_messages[:max_count]):
            role = str(msg.get("role", "")).strip()
            content = msg.get("content")
            entry: Dict[str, Any] = {"idx": idx, "role": role}

            if isinstance(content, str):
                entry["content_preview"] = self.compactor.compact_value(content)
            elif content is None:
                entry["content_preview"] = None
            else:
                entry["content_preview"] = self.compactor.compact_value(content)

            if role == "assistant" and isinstance(msg.get("tool_calls"), list):
                entry["tool_calls_count"] = len(msg.get("tool_calls", []))

            if role == "tool":
                entry["tool_call_id"] = str(msg.get("tool_call_id", "")).strip()

            preview.append(entry)

        omitted = len(request_messages) - len(preview)
        if omitted > 0:
            preview.append({"omitted_messages": omitted})
        return preview

    def _compact_tool_specs(self, tool_specs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        preview: List[Dict[str, Any]] = []
        max_count = self.compactor.config.max_tool_specs
        for spec in tool_specs[:max_count]:
            if not isinstance(spec, dict):
                continue
            name = str(spec.get("name", "")).strip()
            input_schema = spec.get("input_schema", {})
            required: List[str] = []
            if isinstance(input_schema, dict):
                raw_required = input_schema.get("required", [])
                if isinstance(raw_required, list):
                    required = [str(v) for v in raw_required]
            preview.append({"name": name, "required": required})

        omitted = len(tool_specs) - len(preview)
        if omitted > 0:
            preview.append({"omitted_tool_specs": omitted})
        return preview


class RequestMessageService:
    def derive(self, *, model: Any, history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        request_messages: List[Dict[str, Any]]
        normalizer = getattr(model, "_normalize_messages", None)
        if callable(normalizer):
            try:
                normalized = normalizer(history)
                if isinstance(normalized, list):
                    request_messages = normalized
                else:
                    request_messages = history
            except Exception:
                request_messages = history
        else:
            request_messages = history

        model_name = model.__class__.__name__
        system_prompt = str(getattr(model, "system_prompt", "") or "").strip()
        if model_name == "OpenAIModel" and system_prompt:
            return [{"role": "system", "content": system_prompt}, *request_messages]

        return request_messages
