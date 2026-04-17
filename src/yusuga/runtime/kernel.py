from typing import Any, Callable, Dict, List

from yusuga.core.types import ModelResponse
from yusuga.tools.runtime import ToolRegistry


EventHook = Callable[[str], None]


class AgentKernel:
    """Minimal runtime kernel: model -> tool -> result -> model."""

    def __init__(self, model: Any, tools: ToolRegistry, max_iters: int = 8):
        self.model = model
        self.tools = tools
        self.max_iters = max_iters

    def run_turn(self, user_input: str, history: List[Dict[str, Any]], on_event: EventHook | None = None) -> str:
        history.append({"role": "user", "content": user_input})

        for _ in range(self.max_iters):
            response: ModelResponse = self.model.respond(history, self.tools.tool_specs())

            if response.tool_calls:
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
                history.append({"role": "assistant", "content": response.text})

            if not response.tool_calls:
                return response.text

            tool_results_payload = []
            for call in response.tool_calls:
                if on_event:
                    on_event(f"[tool] {call.name}({call.input})")

                result = self.tools.execute(call)
                content = result.content if result.ok else f"Error: {result.error}"

                tool_results_payload.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": result.tool_use_id,
                        "name": result.meta.get("name", call.name),
                        "ok": result.ok,
                        "content": content,
                    }
                )

            history.append({"role": "user", "content": tool_results_payload})

        return "Error: max loop iterations reached"
