import json
import time
from typing import Any, Callable, Dict, List

from yosuga.config.session_log import SessionLogger
from yosuga.core.types import ModelResponse, ToolCall, ToolPolicyDecision
from yosuga.utils.compactor import AutoCompactor, FullCompactor, MicroCompactor
from yosuga.runtime.report import TurnReportWriter
from yosuga.tools.runtime import ToolRegistry


EventHook = Callable[[str], None]
ApprovalHook = Callable[[ToolCall, ToolPolicyDecision], str]


class AgentKernel:
    """Minimal runtime kernel: model -> tool -> result -> model."""

    _LOG_MAX_STRING_CHARS = 200
    _LOG_MAX_LIST_ITEMS = 50
    _LOG_MAX_DICT_ITEMS = 100

    def __init__(
        self,
        model: Any,
        tools: ToolRegistry,
        max_iters: int = 20,
        approval_hook: ApprovalHook | None = None,
        session_logger: SessionLogger | None = None,
        report_writer: TurnReportWriter | None = None,
    ):
        self.model = model
        self.tools = tools
        self.max_iters = max_iters
        self.approval_hook = approval_hook
        self.session_logger = session_logger
        self.report_writer = report_writer
        self._turn_index = 0
        self.micro_compactor = MicroCompactor()
        self.auto_compactor = AutoCompactor(model)
        self.full_compactor = FullCompactor(session_logger)

    def run_turn(self, user_input: str, history: List[Dict[str, Any]], on_event: EventHook | None = None) -> str:
        self._turn_index += 1
        turn_id = self._turn_index
        start_time = time.perf_counter()
        model_calls = 0
        tool_calls = 0
        tool_success = 0
        tool_failures = 0
        tool_retries = 0
        model_tool_arg_parse_errors = 0
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0

        if self.session_logger:
            self.session_logger.log(
                "turn_user_input",
                {
                    "turn_id": turn_id,
                    "text": user_input,
                },
            )

        history.append({"role": "user", "content": user_input})

        for _ in range(self.max_iters):
            try:
                response: ModelResponse = self.model.respond(history, self.tools.tool_specs())
                model_calls += 1
            except Exception as exc:
                if on_event:
                    on_event(f"[compact:full] model error detected: {exc}")

                history = self.full_compactor.archive_and_reset(
                    history=history,
                    current_turn=turn_id,
                    user_input=user_input,
                )

                if self.session_logger:
                    self.session_logger.log(
                        "history_compact_full",
                        {
                            "turn_id": turn_id,
                            "reason": str(exc),
                        },
                    )

                if on_event:
                    on_event("[compact:full] archived and restored lightweight context")

                try:
                    response = self.model.respond(history, self.tools.tool_specs())
                    model_calls += 1
                except Exception as retry_exc:
                    error_text = f"Error: model failed after full compact: {retry_exc}"
                    if self.session_logger:
                        self.session_logger.log(
                            "turn_complete",
                            {
                                "turn_id": turn_id,
                                "answer": error_text,
                            },
                        )
                    self._write_turn_report(
                        turn_id=turn_id,
                        user_input=user_input,
                        answer=error_text,
                        duration_ms=(time.perf_counter() - start_time) * 1000.0,
                        model_calls=model_calls,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=total_tokens,
                        tool_calls=tool_calls,
                        tool_success=tool_success,
                        tool_failures=tool_failures,
                        tool_retries=tool_retries,
                        model_tool_arg_parse_errors=model_tool_arg_parse_errors,
                        max_iters_reached=False,
                    )
                    return error_text

            usage = response.usage or {}
            prompt_tokens += int(usage.get("prompt_tokens", 0) or 0)
            completion_tokens += int(usage.get("completion_tokens", 0) or 0)
            total_tokens += int(usage.get("total_tokens", 0) or 0)
            model_tool_arg_parse_errors += sum(
                1 for e in (response.tool_validation_errors or []) if "invalid arguments" in e
            )

            if on_event and response.text and response.tool_calls:
                on_event(response.text)

            if self.session_logger:
                self.session_logger.log(
                    "model_response",
                    {
                        "turn_id": turn_id,
                        "text": response.text,
                        "reasoning_content": response.reasoning_content,
                        "tool_calls_count": len(response.tool_calls),
                        "usage": usage,
                        "tool_validation_errors": response.tool_validation_errors,
                    },
                )

            if on_event and response.tool_validation_errors:
                on_event("[model:validation] " + " | ".join(response.tool_validation_errors))

            if response.tool_calls:
                if on_event:
                    on_event(f"[model] requested {len(response.tool_calls)} tool call(s)")
                assistant_msg = {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": call.id,
                            "name": call.name,
                            "input": call.input,
                        }
                        for call in response.tool_calls
                    ],
                }
                if response.reasoning_content:
                    assistant_msg["reasoning_content"] = response.reasoning_content
                history.append(assistant_msg)
            else:
                final_text = (response.text or "").strip()
                if response.tool_validation_errors:
                    if final_text:
                        history.append({"role": "assistant", "content": final_text})
                    feedback_text = self._build_tool_validation_feedback(response.tool_validation_errors)
                    if on_event:
                        on_event("[model:retry] " + feedback_text)
                    history.append({"role": "user", "content": feedback_text})
                    continue

                history.append({"role": "assistant", "content": final_text})
                self._write_turn_report(
                    turn_id=turn_id,
                    user_input=user_input,
                    answer=final_text,
                    duration_ms=(time.perf_counter() - start_time) * 1000.0,
                    model_calls=model_calls,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    tool_calls=tool_calls,
                    tool_success=tool_success,
                    tool_failures=tool_failures,
                    tool_retries=tool_retries,
                    model_tool_arg_parse_errors=model_tool_arg_parse_errors,
                    max_iters_reached=False,
                )
                if self.session_logger:
                    self.session_logger.log(
                        "turn_complete",
                        {
                            "turn_id": turn_id,
                            "answer": final_text,
                        },
                    )
                return final_text

            tool_results_payload = []
            for call in response.tool_calls:
                tool_calls += 1
                log_input = self._compact_for_log(call.input)
                log_input_json = json.dumps(log_input, ensure_ascii=False, default=str)
                if on_event:
                    target_path = str(call.input.get("path", "")).strip() if isinstance(call.input, dict) else ""
                    if call.name in {"write_file", "edit_file"}:
                        shown_path = target_path if target_path else "(missing)"
                        on_event(f"[tool] call {call.name} file={shown_path}")
                    else:
                        on_event(f"[tool] call {call.name} args={log_input_json}")

                if self.session_logger:
                    self.session_logger.log(
                        "tool_call",
                        {
                            "turn_id": turn_id,
                            "tool_use_id": call.id,
                            "name": call.name,
                            "input": log_input,
                        },
                    )

                result = self.tools.execute(call, approve=self.approval_hook, on_event=on_event)
                if result.ok:
                    tool_success += 1
                else:
                    tool_failures += 1
                tool_retries += int(result.meta.get("retry_count", 0) or 0)

                if self.session_logger:
                    self.session_logger.log(
                        "tool_result",
                        {
                            "turn_id": turn_id,
                            "tool_use_id": result.tool_use_id,
                            "name": result.meta.get("name", call.name),
                            "ok": result.ok,
                            "error": result.error,
                            "meta": result.meta,
                        },
                    )

                tool_results_payload.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": result.tool_use_id,
                        "name": result.meta.get("name", call.name),
                        "ok": result.ok,
                        "content": result.content,
                        "error": result.error,
                        "meta": result.meta,
                    }
                )

            # Apply Micro Compact before appending to history
            compacted_history, chars_released = self.micro_compactor.compact_history(history)
            if chars_released > 0 and on_event:
                on_event(f"[compact:micro] released {chars_released} chars")
            history = compacted_history

            history.append({"role": "user", "content": tool_results_payload})

            # Apply Auto Compact when token usage is near context limit.
            if self.auto_compactor.should_compact(usage):
                auto_compacted_history, estimated_saved = self.auto_compactor.compact_history(history)
                if estimated_saved > 0:
                    history = auto_compacted_history
                    if on_event:
                        on_event(f"[compact:auto] estimated saved {estimated_saved} chars")
                    if self.session_logger:
                        self.session_logger.log(
                            "history_compact_auto",
                            {
                                "turn_id": turn_id,
                                "estimated_saved": estimated_saved,
                            },
                        )

        # Final fallback: full compact once before giving up on max-iter exhaustion.
        if on_event:
            on_event("[compact:full] max iterations reached, trying one final compact-retry")
        history = self.full_compactor.archive_and_reset(
            history=history,
            current_turn=turn_id,
            user_input=user_input,
        )
        try:
            final_retry_response: ModelResponse = self.model.respond(history, self.tools.tool_specs())
            model_calls += 1
            final_retry_text = (final_retry_response.text or "").strip()
            if final_retry_text and not final_retry_response.tool_calls:
                history.append({"role": "assistant", "content": final_retry_text})
                self._write_turn_report(
                    turn_id=turn_id,
                    user_input=user_input,
                    answer=final_retry_text,
                    duration_ms=(time.perf_counter() - start_time) * 1000.0,
                    model_calls=model_calls,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    tool_calls=tool_calls,
                    tool_success=tool_success,
                    tool_failures=tool_failures,
                    tool_retries=tool_retries,
                    model_tool_arg_parse_errors=model_tool_arg_parse_errors,
                    max_iters_reached=False,
                )
                if self.session_logger:
                    self.session_logger.log(
                        "turn_complete",
                        {
                            "turn_id": turn_id,
                            "answer": final_retry_text,
                        },
                    )
                return final_retry_text
        except Exception:
            pass

        if self.session_logger:
            self.session_logger.log(
                "turn_complete",
                {
                    "turn_id": turn_id,
                    "answer": "Error: max loop iterations reached",
                },
            )
        self._write_turn_report(
            turn_id=turn_id,
            user_input=user_input,
            answer="Error: max loop iterations reached",
            duration_ms=(time.perf_counter() - start_time) * 1000.0,
            model_calls=model_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            tool_calls=tool_calls,
            tool_success=tool_success,
            tool_failures=tool_failures,
            tool_retries=tool_retries,
            model_tool_arg_parse_errors=model_tool_arg_parse_errors,
            max_iters_reached=True,
        )
        return "Error: max loop iterations reached"

    def _write_turn_report(
        self,
        *,
        turn_id: int,
        user_input: str,
        answer: str,
        duration_ms: float,
        model_calls: int,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        tool_calls: int,
        tool_success: int,
        tool_failures: int,
        tool_retries: int,
        model_tool_arg_parse_errors: int,
        max_iters_reached: bool,
    ) -> None:
        if not self.report_writer:
            return
        self.report_writer.write_turn(
            {
                "turn_id": turn_id,
                "user_input": user_input,
                "answer": answer,
                "duration_ms": round(duration_ms, 2),
                "model_calls": model_calls,
                "model": {
                    "tool_argument_parse_errors": model_tool_arg_parse_errors,
                },
                "tokens": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                },
                "tools": {
                    "calls": tool_calls,
                    "success": tool_success,
                    "failures": tool_failures,
                    "retries": tool_retries,
                },
                "max_iters_reached": max_iters_reached,
            }
        )

    @staticmethod
    def _build_tool_validation_feedback(errors: List[str]) -> str:
        return (
            "Tool argument validation failed: "
            + " | ".join(errors)
            + ". Please retry with valid JSON arguments and required fields."
        )

    def _compact_for_log(self, value: Any) -> Any:
        if isinstance(value, str):
            if len(value) <= self._LOG_MAX_STRING_CHARS:
                return value
            omitted = len(value) - self._LOG_MAX_STRING_CHARS
            return value[: self._LOG_MAX_STRING_CHARS] + f"... [truncated {omitted} chars]"

        if isinstance(value, list):
            head = [self._compact_for_log(v) for v in value[: self._LOG_MAX_LIST_ITEMS]]
            if len(value) > self._LOG_MAX_LIST_ITEMS:
                head.append(f"... [truncated {len(value) - self._LOG_MAX_LIST_ITEMS} items]")
            return head

        if isinstance(value, dict):
            compacted: Dict[str, Any] = {}
            items = list(value.items())
            for k, v in items[: self._LOG_MAX_DICT_ITEMS]:
                compacted[str(k)] = self._compact_for_log(v)
            if len(items) > self._LOG_MAX_DICT_ITEMS:
                compacted["__truncated_keys__"] = len(items) - self._LOG_MAX_DICT_ITEMS
            return compacted

        return value
