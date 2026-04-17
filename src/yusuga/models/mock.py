import uuid
from typing import Any, Dict, List

from yusuga.core.types import ModelResponse, ToolCall


class MockModel:
    """A deterministic local model used for bootstrapping the kernel."""

    def respond(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> ModelResponse:
        if not messages:
            return ModelResponse(text="No messages yet.")

        last = messages[-1].get("content")

        if isinstance(last, list):
            for block in last:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    tool_name = block.get("name", "tool")
                    content = block.get("content", "")
                    return ModelResponse(text=f"[{tool_name}]\n{content}")
            return ModelResponse(text="Received tool results.")

        if not isinstance(last, str):
            return ModelResponse(text="Unsupported message payload.")

        query = last.strip()
        if not query:
            return ModelResponse(text="Please input something.")

        if query in ("/help", "help"):
            return ModelResponse(
                text=(
                    "Commands:\n"
                    "  help or /help\n"
                    "  echo <text>\n"
                    "  ls [path]\n"
                    "  read <path>\n"
                    "  bash <command>\n"
                    "  exit\n"
                )
            )

        call = self._parse_tool_call(query)
        if call:
            return ModelResponse(tool_calls=[call])

        return ModelResponse(
            text=(
                "MockModel response: no tool needed. "
                "Try: echo hello, ls ., read coding-agent-architecture-plan.md"
            )
        )

    def _parse_tool_call(self, query: str) -> ToolCall | None:
        low = query.lower()

        if low.startswith("echo "):
            return ToolCall(id=self._id(), name="echo", input={"text": query[5:]})

        if low == "ls" or low.startswith("ls "):
            path = query[3:].strip() if len(query) > 2 else "."
            return ToolCall(id=self._id(), name="list_dir", input={"path": path or "."})

        if low.startswith("read "):
            return ToolCall(id=self._id(), name="read_file", input={"path": query[5:].strip()})

        if low.startswith("bash "):
            return ToolCall(id=self._id(), name="bash", input={"command": query[5:]})

        return None

    @staticmethod
    def _id() -> str:
        return f"call_{uuid.uuid4().hex[:10]}"
