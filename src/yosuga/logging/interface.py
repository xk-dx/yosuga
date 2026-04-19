from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from yosuga.core.types import ToolCall, ToolResult
from yosuga.logging.controllers import KernelLogController
from yosuga.logging.executors import JsonlLogExecutor, SessionStore
from yosuga.logging.services import LogCompactConfig, LogCompactionService, LogPayloadService, RequestMessageService


class RuntimeLogger:
    """Unified external logger interface used by kernel and CLI."""

    def __init__(
        self,
        *,
        state_root: Path,
        relative_dir: str,
        model: Any | None = None,
        session_id: str | None = None,
        config: LogCompactConfig | None = None,
    ):
        self._store = SessionStore(state_root=state_root, relative_dir=relative_dir, session_id=session_id)
        self._executor = JsonlLogExecutor(self._store)
        self._compactor = LogCompactionService(config=config)
        self._payload_service = LogPayloadService(compactor=self._compactor)
        self._request_service = RequestMessageService()
        self._controller = KernelLogController(
            model=model,
            executor=self._executor,
            payload_service=self._payload_service,
            request_service=self._request_service,
        )

    @property
    def session_id(self) -> str:
        return self._store.session_id

    @property
    def session_dir(self) -> Path:
        return self._store.session_dir

    @property
    def path(self) -> Path:
        return self._store.path

    def bind_model(self, model: Any) -> None:
        self._controller.model = model

    def compact_value(self, value: Any) -> Any:
        return self._controller.compact_value(value)

    def log_turn_user_input(self, *, turn_id: int, text: str) -> None:
        self._controller.log_turn_user_input(turn_id=turn_id, text=text)

    def log_model_request(self, *, turn_id: int, phase: str, history: List[Dict[str, Any]], tool_specs: List[Dict[str, Any]]) -> None:
        self._controller.log_model_request(turn_id=turn_id, phase=phase, history=history, tool_specs=tool_specs)

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
        self._controller.log_model_response(
            turn_id=turn_id,
            text=text,
            reasoning_content=reasoning_content,
            tool_calls_count=tool_calls_count,
            usage=usage,
            tool_validation_errors=tool_validation_errors,
        )

    def log_tool_call(self, *, turn_id: int, call: ToolCall) -> None:
        self._controller.log_tool_call(turn_id=turn_id, call=call)

    def log_tool_result(self, *, turn_id: int, call_name: str, result: ToolResult, content_preview: str) -> None:
        self._controller.log_tool_result(turn_id=turn_id, call_name=call_name, result=result, content_preview=content_preview)

    def log_history_compact_full(self, *, turn_id: int, reason: str) -> None:
        self._controller.log_history_compact_full(turn_id=turn_id, reason=reason)

    def log_history_compact_auto(self, *, turn_id: int, estimated_saved: Any) -> None:
        self._controller.log_history_compact_auto(turn_id=turn_id, estimated_saved=estimated_saved)

    def log_turn_complete(self, *, turn_id: int, answer: str) -> None:
        self._controller.log_turn_complete(turn_id=turn_id, answer=answer)

    def log_custom(self, event_type: str, payload: Dict[str, Any], *, compact: bool = True) -> None:
        self._controller.log_custom(event_type, payload, compact=compact)

    # Compatibility shim for legacy call sites using session_logger.log(...).
    def log(self, event_type: str, payload: Dict[str, Any]) -> None:
        self.log_custom(event_type, payload, compact=False)
