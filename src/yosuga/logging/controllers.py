from __future__ import annotations

from typing import Any, Dict, List

from yosuga.core.types import ToolCall, ToolResult
from yosuga.logging.executors import JsonlLogExecutor
from yosuga.logging.services import LogPayloadService, RequestMessageService


class KernelLogController:
    """Controller layer: stable external logging API for kernel stages."""

    def __init__(
        self,
        *,
        model: Any,
        executor: JsonlLogExecutor,
        payload_service: LogPayloadService,
        request_service: RequestMessageService,
    ):
        self.model = model
        self.executor = executor
        self.payload_service = payload_service
        self.request_service = request_service

    def compact_value(self, value: Any) -> Any:
        return self.payload_service.compactor.compact_value(value)

    def log_turn_user_input(self, *, turn_id: int, text: str) -> None:
        self.executor.append("turn_user_input", self.payload_service.turn_user_input_payload(turn_id=turn_id, text=text))

    def log_model_request(
        self,
        *,
        turn_id: int,
        phase: str,
        history: List[Dict[str, Any]],
        tool_specs: List[Dict[str, Any]],
    ) -> None:
        request_messages = self.request_service.derive(model=self.model, history=history)
        payload = self.payload_service.model_request_payload(
            turn_id=turn_id,
            phase=phase,
            request_messages=request_messages,
            tool_specs=tool_specs,
        )
        self.executor.append("model_request", payload)

    def log_model_response(
        self,
        *,
        turn_id: int,
        text: str,
        reasoning_content: str,
        tool_calls_count: int,
        usage: Dict[str, Any],
        tool_validation_errors: List[str],
    ) -> None:
        payload = self.payload_service.model_response_payload(
            turn_id=turn_id,
            text=text,
            reasoning_content=reasoning_content,
            tool_calls_count=tool_calls_count,
            usage=usage,
            tool_validation_errors=tool_validation_errors,
        )
        self.executor.append("model_response", payload)

    def log_tool_call(self, *, turn_id: int, call: ToolCall) -> None:
        self.executor.append("tool_call", self.payload_service.tool_call_payload(turn_id=turn_id, call=call))

    def log_tool_result(self, *, turn_id: int, call_name: str, result: ToolResult, content_preview: str) -> None:
        payload = self.payload_service.tool_result_payload(
            turn_id=turn_id,
            call_name=call_name,
            result=result,
            content_preview=content_preview,
        )
        self.executor.append("tool_result", payload)

    def log_history_compact_full(self, *, turn_id: int, reason: str) -> None:
        payload = self.payload_service.history_compact_payload(turn_id=turn_id, reason_or_saved=reason, field="reason")
        self.executor.append("history_compact_full", payload)

    def log_history_compact_auto(self, *, turn_id: int, estimated_saved: Any) -> None:
        payload = self.payload_service.history_compact_payload(
            turn_id=turn_id,
            reason_or_saved=estimated_saved,
            field="estimated_saved",
        )
        self.executor.append("history_compact_auto", payload)

    def log_turn_complete(self, *, turn_id: int, answer: str) -> None:
        self.executor.append("turn_complete", self.payload_service.turn_complete_payload(turn_id=turn_id, answer=answer))

    def log_custom(self, event_type: str, payload: Dict[str, Any], *, compact: bool = True) -> None:
        safe_payload = self.payload_service.compactor.compact_value(payload) if compact else payload
        self.executor.append(event_type, safe_payload)
