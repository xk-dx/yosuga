import os
from typing import Any, Dict, List

from yosuga.config.instruction_system import load_engineered_system_prompt
from yosuga.core.types import ModelResponse, ToolCall


class AnthropicModel:
    def __init__(
        self,
        api_base: str,
        api_key: str,
        model: str,
        max_tokens: int = 4096,
        system_prompt: str = "",
    ):
        try:
            from anthropic import Anthropic
        except Exception as exc:
            raise RuntimeError("Missing dependency: anthropic. Install with: pip install anthropic") from exc

        self.model = model
        self.max_tokens = max_tokens
        self.system_prompt = system_prompt
        self.client = Anthropic(api_key=api_key, base_url=api_base)

    def respond(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> ModelResponse:
        request_messages = self._normalize_messages(messages)

        try:
            response = self.client.messages.create(
                model=self.model,
                messages=request_messages,
                tools=tools,
                max_tokens=self.max_tokens,
                system=self.system_prompt or None,
            )
        except Exception as exc:
            return ModelResponse(text=f"Anthropic API error: {exc}")

        text_parts: List[str] = []
        calls: List[ToolCall] = []
        usage_obj = getattr(response, "usage", None)
        prompt_tokens = int(getattr(usage_obj, "input_tokens", 0) or 0)
        completion_tokens = int(getattr(usage_obj, "output_tokens", 0) or 0)
        usage = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                calls.append(ToolCall(id=block.id, name=block.name, input=dict(block.input)))

        return ModelResponse(text="\n".join(text_parts).strip(), tool_calls=calls, usage=usage)

    def _normalize_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for message in messages:
            role = message.get("role")
            if role not in ("user", "assistant"):
                continue

            content = message.get("content", "")
            if isinstance(content, str):
                normalized.append({"role": role, "content": content})
                continue

            if isinstance(content, list):
                blocks = []
                for item in content:
                    if not isinstance(item, dict):
                        continue
                    t = item.get("type")
                    if t == "tool_use":
                        blocks.append({"type": "tool_use", "id": item.get("id"), "name": item.get("name"), "input": item.get("input", {})})
                    elif t == "tool_result":
                        blocks.append({"type": "tool_result", "tool_use_id": item.get("tool_use_id"), "content": item.get("content", ""), "is_error": not bool(item.get("ok", True))})
                if blocks:
                    normalized.append({"role": role, "content": blocks})

        if not normalized:
            normalized.append({"role": "user", "content": ""})
        return normalized


def load_anthropic_from_env(*, workspace_root: Any | None = None, role: str = "lead") -> AnthropicModel:
    api_base = os.getenv("ANTHROPIC_API_BASE", "").strip()
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    model = os.getenv("ANTHROPIC_MODEL", "").strip()

    missing = []
    if not api_base:
        missing.append("ANTHROPIC_API_BASE")
    if not api_key:
        missing.append("ANTHROPIC_API_KEY")
    if not model:
        missing.append("ANTHROPIC_MODEL")

    if missing:
        raise RuntimeError(f"Missing environment variables: {', '.join(missing)}")

    return AnthropicModel(
        api_base=api_base,
        api_key=api_key,
        model=model,
        system_prompt=load_engineered_system_prompt(workspace_root=workspace_root, role=role).prompt,
    )
