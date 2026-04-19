import json
import time
from typing import Any, Callable, Dict, List

from yosuga.core.types import ModelResponse, ToolCall, ToolPolicyDecision
from yosuga.logging import RuntimeLogger
from yosuga.utils.compactor import AutoCompactor, FullCompactor, MicroCompactor
from yosuga.runtime.report import TurnReportWriter
from yosuga.tools.runtime import ToolRegistry


EventHook = Callable[[str], None]
ApprovalHook = Callable[[ToolCall, ToolPolicyDecision], str]


class AgentKernel:
    """Minimal runtime kernel: model -> tool -> result -> model."""

    def __init__(
        self,
        model: Any,
        tools: ToolRegistry,
        max_iters: int = 40,
        approval_hook: ApprovalHook | None = None,
        logger: RuntimeLogger | None = None,
        report_writer: TurnReportWriter | None = None,
    ):
        self.model = model
        self.tools = tools
        self.max_iters = max_iters
        self.approval_hook = approval_hook
        self.logger = logger
        self.report_writer = report_writer
        self._turn_index = 0
        self.micro_compactor = MicroCompactor()
        self.auto_compactor = AutoCompactor(model)
        self.full_compactor = FullCompactor(logger)
        if self.logger:
            self.logger.bind_model(model)

    def set_turn_index(self, turn_index: int) -> None:
        self._turn_index = max(0, int(turn_index))

    def get_turn_index(self) -> int:
        return self._turn_index

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
        micro_compact_events = 0
        micro_chars_released_total = 0
        auto_compact_events = 0
        auto_estimated_saved_total = 0
        full_compact_events = 0

        if self.logger:
            self.logger.log_turn_user_input(turn_id=turn_id, text=user_input)

        history.append({"role": "user", "content": user_input})

        for _ in range(self.max_iters):
            try:
                tool_specs = self.tools.tool_specs()
                if self.logger:
                    self.logger.log_model_request(
                        turn_id=turn_id,
                        phase="loop",
                        history=history,
                        tool_specs=tool_specs,
                    )
                response: ModelResponse = self.model.respond(history, tool_specs)
                model_calls += 1
            except Exception as exc:
                if on_event:
                    on_event(f"[compact:full] model error detected: {exc}")

                history = self.full_compactor.archive_and_reset(
                    history=history,
                    current_turn=turn_id,
                    user_input=user_input,
                )
                full_compact_events += 1

                if self.logger:
                    self.logger.log_history_compact_full(turn_id=turn_id, reason=str(exc))

                if on_event:
                    on_event("[compact:full] archived and restored lightweight context")

                try:
                    tool_specs = self.tools.tool_specs()
                    if self.logger:
                        self.logger.log_model_request(
                            turn_id=turn_id,
                            phase="full_compact_retry",
                            history=history,
                            tool_specs=tool_specs,
                        )
                    response = self.model.respond(history, tool_specs)
                    model_calls += 1
                except Exception as retry_exc:
                    error_text = f"Error: model failed after full compact: {retry_exc}"
                    if self.logger:
                        self.logger.log_turn_complete(turn_id=turn_id, answer=error_text)
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
                        micro_compact_events=micro_compact_events,
                        micro_chars_released_total=micro_chars_released_total,
                        auto_compact_events=auto_compact_events,
                        auto_estimated_saved_total=auto_estimated_saved_total,
                        full_compact_events=full_compact_events,
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

            if self.logger:
                self.logger.log_model_response(
                    turn_id=turn_id,
                    text=response.text,
                    reasoning_content=response.reasoning_content,
                    tool_calls_count=len(response.tool_calls),
                    usage=usage,
                    tool_validation_errors=response.tool_validation_errors,
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
                    micro_compact_events=micro_compact_events,
                    micro_chars_released_total=micro_chars_released_total,
                    auto_compact_events=auto_compact_events,
                    auto_estimated_saved_total=auto_estimated_saved_total,
                    full_compact_events=full_compact_events,
                    max_iters_reached=False,
                )
                if self.logger:
                    self.logger.log_turn_complete(turn_id=turn_id, answer=final_text)
                return final_text

            tool_results_payload = []
            #工具调用循环
            for call in response.tool_calls:
                tool_calls += 1
                log_input = self.logger.compact_value(call.input) if self.logger else call.input
                log_input_json = json.dumps(log_input, ensure_ascii=False, default=str)
                if on_event:
                    target_path = str(call.input.get("path", "")).strip() if isinstance(call.input, dict) else ""
                    if call.name in {"write_file", "edit_file"}:
                        shown_path = target_path if target_path else "(missing)"
                        on_event(f"[tool] call {call.name} file={shown_path}")
                    else:
                        on_event(f"[tool] call {call.name} args={log_input_json}")

                if self.logger:
                    self.logger.log_tool_call(turn_id=turn_id, call=call)

                result = self.tools.execute(call, approve=self.approval_hook, on_event=on_event)
                if result.ok:
                    tool_success += 1
                else:
                    tool_failures += 1
                tool_retries += int(result.meta.get("retry_count", 0) or 0)

                combined_content = self._build_tool_result_content(
                    content=result.content,
                    error=result.error,
                    meta=result.meta,
                )

                if self.logger:
                    self.logger.log_tool_result(
                        turn_id=turn_id,
                        call_name=call.name,
                        result=result,
                        content_preview=combined_content,
                    )

                tool_results_payload.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": result.tool_use_id,
                        "name": result.meta.get("name", call.name),
                        "ok": result.ok,                        
                        "content": combined_content,
                        "error": result.error,
                        "meta": result.meta,
                    }
                )

            # Apply Micro Compact before appending to history
            compacted_history, chars_released = self.micro_compactor.compact_history(history)
            if chars_released > 0 and on_event:
                on_event(f"[compact:micro] released {chars_released} chars")
            if chars_released > 0:
                micro_compact_events += 1
                micro_chars_released_total += int(chars_released)
            history[:] = compacted_history

            history.append({"role": "user", "content": tool_results_payload})

            # Apply Auto Compact when token usage is near context limit.
            if self.auto_compactor.should_compact(usage):
                auto_compacted_history, estimated_saved = self.auto_compactor.compact_history(history)
                if estimated_saved > 0:
                    history[:] = auto_compacted_history
                    auto_compact_events += 1
                    auto_estimated_saved_total += int(estimated_saved)
                    if on_event:
                        on_event(f"[compact:auto] estimated saved {estimated_saved} chars")
                    if self.logger:
                        self.logger.log_history_compact_auto(turn_id=turn_id, estimated_saved=estimated_saved)

        # Final fallback: full compact once before giving up on max-iter exhaustion.
        if on_event:
            on_event("[compact:full] max iterations reached, trying one final compact-retry")
        new_history = self.full_compactor.archive_and_reset(
            history=history,
            current_turn=turn_id,
            user_input=user_input,
        )
        full_compact_events += 1
        history[:] = new_history
        try:  # 最后一次尝试
            history.append(
                {
                    "role": "user",
                    "content": (
                        "System notice: max_iter limit reached. "
                        "Please provide a direct final response now, resolve any pending tool-call context as failed/expired, "
                        "and do not request any additional tool calls."
                    ),
                }
            )
            tool_specs = self.tools.tool_specs()
            if self.logger:
                self.logger.log_model_request(
                    turn_id=turn_id,
                    phase="max_iter_final_retry",
                    history=history,
                    tool_specs=tool_specs,
                )
            final_retry_response: ModelResponse = self.model.respond(history, tool_specs)
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
                    micro_compact_events=micro_compact_events,
                    micro_chars_released_total=micro_chars_released_total,
                    auto_compact_events=auto_compact_events,
                    auto_estimated_saved_total=auto_estimated_saved_total,
                    full_compact_events=full_compact_events,
                    max_iters_reached=False,
                )
                if self.logger:
                    self.logger.log_turn_complete(turn_id=turn_id, answer=final_retry_text)
                return final_retry_text
        except Exception:
            pass

        if self.logger:
            self.logger.log_turn_complete(turn_id=turn_id, answer="Error: max loop iterations reached")
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
            micro_compact_events=micro_compact_events,
            micro_chars_released_total=micro_chars_released_total,
            auto_compact_events=auto_compact_events,
            auto_estimated_saved_total=auto_estimated_saved_total,
            full_compact_events=full_compact_events,
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
        micro_compact_events: int,
        micro_chars_released_total: int,
        auto_compact_events: int,
        auto_estimated_saved_total: int,
        full_compact_events: int,
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
                "compaction": {
                    "micro": {
                        "events": micro_compact_events,
                        "chars_released_total": micro_chars_released_total,
                    },
                    "auto": {
                        "events": auto_compact_events,
                        "estimated_saved_total": auto_estimated_saved_total,
                    },
                    "full": {
                        "events": full_compact_events,
                    },
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

    def _build_tool_result_content(self, *, content: Any, error: str, meta: Dict[str, Any]) -> str:
        parts: List[str] = []

        content_text = str(content or "").strip()

        if content_text:
            parts.append(content_text)

        err = (error or "").strip()
        if err:
            parts.append(f"error: {err}")

        policy_code = str((meta or {}).get("policy_code", "")).strip()
        if policy_code:
            parts.append(f"policy_code: {policy_code}")

        policy_reason = str((meta or {}).get("policy_reason", "")).strip()
        if policy_reason:
            parts.append(f"policy_reason: {policy_reason}")

        policy_suggestion = str((meta or {}).get("policy_suggestion", "")).strip()
        if policy_suggestion:
            parts.append(f"policy_suggestion: {policy_suggestion}")

        return "\n".join(parts)

