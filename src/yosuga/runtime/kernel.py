import time
from typing import Any, Callable, Dict, List

from yosuga.config.session_log import SessionLogger
from yosuga.core.types import ToolCall, ToolPolicyDecision
from yosuga.core.types import ModelResponse
from yosuga.runtime.report import TurnReportWriter
from yosuga.tools.runtime import ToolRegistry


EventHook = Callable[[str], None]
ApprovalHook = Callable[[ToolCall, ToolPolicyDecision], bool]


class AgentKernel:
    """Minimal runtime kernel: model -> tool -> result -> model."""

    def __init__(
        self,
        model: Any,
        tools: ToolRegistry,
        max_iters: int = 8,
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
            response: ModelResponse = self.model.respond(history, self.tools.tool_specs())
            model_calls += 1
            usage = response.usage or {}
            prompt_tokens += int(usage.get("prompt_tokens", 0) or 0)
            completion_tokens += int(usage.get("completion_tokens", 0) or 0)
            total_tokens += int(usage.get("total_tokens", 0) or 0)
            model_tool_arg_parse_errors += sum(
                1 for e in (response.tool_validation_errors or []) if "invalid arguments" in e
            )

            if on_event and response.text and response.tool_calls:
                text_preview = response.text.strip().replace("\n", " ")
                if len(text_preview) > 240:
                    text_preview = text_preview[:240] + "..."
                on_event(f"[model:text] {text_preview}")

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
                on_event(
                    "[model:validation] "
                    + " | ".join(response.tool_validation_errors)
                )

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
                if on_event:
                    on_event("[model] final response ready")
                history.append({"role": "assistant", "content": response.text})

            if not response.tool_calls:
                self._write_turn_report(
                    turn_id=turn_id,
                    user_input=user_input,
                    answer=response.text,
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
                            "answer": response.text,
                        },
                    )
                return response.text

            tool_results_payload = []
            for call in response.tool_calls:
                tool_calls += 1
                if on_event:
                    input_keys = ", ".join(sorted(call.input.keys())) if call.input else "(no args)"
                    on_event(f"[tool] call {call.name} args={input_keys}")

                if self.session_logger:
                    self.session_logger.log(
                        "tool_call",
                        {
                            "turn_id": turn_id,
                            "tool_use_id": call.id,
                            "name": call.name,
                            "input": call.input,
                        },
                    )

                result = self.tools.execute(call, approve=self.approval_hook)
                if result.ok:
                    tool_success += 1
                else:
                    tool_failures += 1
                tool_retries += int(result.meta.get("retry_count", 0) or 0)
                if result.ok:
                    content = result.content
                else:
                    suggestion = result.meta.get("policy_suggestion", "")
                    if suggestion:
                        content = f"Error: {result.error}\nSuggestion: {suggestion}"
                    else:
                        content = f"Error: {result.error}"

                if self.session_logger:
                    self.session_logger.log(
                        "tool_result",
                        {
                            "turn_id": turn_id,
                            "tool_use_id": result.tool_use_id,
                            "name": result.meta.get("name", call.name),
                            "ok": result.ok,
                            "error": result.error or "",
                            "meta": result.meta,
                            "content": content,
                        },
                    )

                if on_event:
                    status = "ok" if result.ok else "error"
                    on_event(f"[tool] result {result.meta.get('name', call.name)} => {status}")

                tool_results_payload.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": result.tool_use_id,
                        "name": result.meta.get("name", call.name),
                        "ok": result.ok,
                        "content": content,
                        "meta": result.meta,
                    }
                )

            history.append({"role": "user", "content": tool_results_payload})

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
