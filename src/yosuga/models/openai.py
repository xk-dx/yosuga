import ast
import json
import os
from typing import Any, Dict, List

from yosuga.config.instruction_system import load_engineered_system_prompt
from yosuga.core.types import ModelResponse, ToolCall


class OpenAIModel:
    def __init__(
        self,
        api_base: str,
        api_key: str,
        model: str,
        max_tokens: int = 4096,
        system_prompt: str = "",
    ):
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Missing dependency: openai. Install with: pip install openai") from exc

        self.model = model
        self.max_tokens = max_tokens
        self.system_prompt = system_prompt
        self.client = OpenAI(api_key=api_key, base_url=api_base.rstrip("/"))

    def respond(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> ModelResponse:
        request_messages = self._normalize_messages(messages)
        if self.system_prompt:
            request_messages = [{"role": "system", "content": self.system_prompt}, *request_messages]

        openai_tools = [self._to_openai_tool(t) for t in tools] if tools else None

        request_kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": request_messages,
            "tools": openai_tools,
            "max_tokens": self.max_tokens,
        }

        # Some OpenAI-compatible providers enable "thinking" by default and
        # require reasoning fields in tool-call turns. Disable thinking when
        # tools are available to reduce token cost and avoid provider 400s.
        disable_thinking_on_tool = os.getenv("OPENAI_DISABLE_THINKING_ON_TOOL", "true").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if disable_thinking_on_tool and openai_tools:
            request_kwargs["extra_body"] = {
                "thinking": {"type": "disabled"}
            }

        try:
            response = self.client.chat.completions.create(**request_kwargs)
        except Exception as exc:
            return ModelResponse(text=f"OpenAI API error: {exc}")

        text_parts: List[str] = []
        calls: List[ToolCall] = []
        tool_arg_warnings: List[str] = []
        choice = response.choices[0]
        reasoning_content = getattr(choice.message, "reasoning_content", "") or ""
        usage_obj = getattr(response, "usage", None)
        usage = {
            "prompt_tokens": int(getattr(usage_obj, "prompt_tokens", 0) or 0),
            "completion_tokens": int(getattr(usage_obj, "completion_tokens", 0) or 0),
            "total_tokens": int(getattr(usage_obj, "total_tokens", 0) or 0),
        }

        required_fields_by_tool: Dict[str, List[str]] = {}
        for spec in tools:
            if not isinstance(spec, dict):
                continue
            tool_name = str(spec.get("name", "") or "")
            input_schema = spec.get("input_schema", {})
            required = []
            if isinstance(input_schema, dict):
                raw_required = input_schema.get("required", [])
                if isinstance(raw_required, list):
                    required = [str(x) for x in raw_required]
            if tool_name:
                required_fields_by_tool[tool_name] = required

        if choice.message.content:
            text_parts.append(choice.message.content)

        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                fn = tc.function
                try:
                    args = self._parse_tool_arguments(fn.arguments)
                except ValueError as exc:
                    tool_arg_warnings.append(f"exists {fn.name} error: invalid arguments ({exc})")
                    continue

                required_fields = required_fields_by_tool.get(fn.name, [])
                missing_required = [
                    key for key in required_fields if key not in args or args.get(key) in (None, "")
                ]
                if missing_required:
                    missing_text = ", ".join(missing_required)
                    tool_arg_warnings.append(f"{fn.name}: missing required arguments: {missing_text}")
                    continue

                calls.append(ToolCall(id=tc.id, name=fn.name, input=args))

        return ModelResponse(
            text="\n".join(text_parts).strip(),
            tool_calls=calls,
            reasoning_content=reasoning_content,
            usage=usage,
            tool_validation_errors=tool_arg_warnings,
        )

    @staticmethod
    def _parse_tool_arguments(raw_arguments: Any) -> Dict[str, Any]:
        if isinstance(raw_arguments, dict):
            return raw_arguments

        if raw_arguments is None:
            raise ValueError("arguments is null")

        if not isinstance(raw_arguments, str):
            raise ValueError(f"arguments must be object or JSON string, got {type(raw_arguments).__name__}")

        payload = raw_arguments.strip()
        if not payload:
            raise ValueError("arguments is empty string")

        parsed: Any
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            try:
                # Fallback for some OpenAI-compatible providers that return Python-style dict literals.
                parsed = ast.literal_eval(payload)
            except (SyntaxError, ValueError) as exc:
                raise ValueError("cannot parse arguments as JSON object") from exc

        if not isinstance(parsed, dict):
            raise ValueError(f"arguments is {type(parsed).__name__}, expected object")

        return parsed


    def _normalize_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []

        for message in messages:
            role = message.get("role")
            if role not in ("user", "assistant"):
                continue

            content = message.get("content")
            if isinstance(content, str):
                normalized.append({"role": role, "content": content})
                continue

            if isinstance(content, list):
                if role == "assistant":
                    tool_calls = []
                    reasoning_content = message.get("reasoning_content", "")
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "tool_use":
                            tool_calls.append(
                                {
                                    "id": item.get("id"),
                                    "type": "function",
                                    "function": {
                                        "name": item.get("name"),
                                        "arguments": json.dumps(item.get("input", {}), ensure_ascii=False),
                                    },
                                }
                            )
                    if tool_calls:
                        normalized.append(
                            {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": tool_calls,
                                "reasoning_content": reasoning_content,
                            }
                        )
                elif role == "user":
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "tool_result":
                            normalized.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": item.get("tool_use_id"),
                                    "content": item.get("content", ""),
                                }
                            )

        if not normalized:
            normalized.append({"role": "user", "content": ""})
        return normalized

    @staticmethod
    def _to_openai_tool(tool_spec: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": tool_spec.get("name"),
                "description": tool_spec.get("description", ""),
                "parameters": tool_spec.get(
                    "input_schema",
                    {
                        "type": "object",
                        "properties": {},
                    },
                ),
            },
        }


def load_openai_from_env(*, workspace_root: Any | None = None, role: str = "lead") -> OpenAIModel:
    api_base = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1").strip()
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("OPENAI_MODEL", "gpt-4").strip()

    if not api_key:
        raise RuntimeError("Missing environment variable: OPENAI_API_KEY")
    if not model:
        raise RuntimeError("Missing environment variable: OPENAI_MODEL")

    return OpenAIModel(
        api_base=api_base,
        api_key=api_key,
        model=model,
        system_prompt=load_engineered_system_prompt(workspace_root=workspace_root, role=role).prompt,
    )
