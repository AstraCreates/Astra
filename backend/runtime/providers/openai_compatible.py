"""OpenAI-compatible provider adapter used by OpenRouter and local endpoints."""
from __future__ import annotations

import json
import uuid
from typing import Any

from backend.runtime.providers.base import (
    ProviderCapabilities,
    ProviderRequest,
    ProviderResponse,
    ToolInvocation,
)


class OpenAICompatibleAdapter:
    def __init__(self, client: Any, *, capabilities: ProviderCapabilities | None = None):
        self.client = client
        self.capabilities = capabilities or ProviderCapabilities(native_tool_calls=True, parallel_tool_calls=True)

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        kwargs: dict[str, Any] = {
            "model": request.model,
            "messages": request.messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.tools and self.capabilities.native_tool_calls:
            kwargs["tools"] = request.tools
            kwargs["tool_choice"] = "auto"
        response = self.client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        message = choice.message
        calls: list[ToolInvocation] = []
        for call in getattr(message, "tool_calls", None) or []:
            raw_args = getattr(call.function, "arguments", "{}") or "{}"
            try:
                args = json.loads(raw_args)
            except Exception:
                args = {}
            calls.append(ToolInvocation(
                id=getattr(call, "id", None) or f"call_{uuid.uuid4().hex[:10]}",
                name=call.function.name,
                arguments=args,
            ))
        usage_obj = getattr(response, "usage", None)
        usage = {
            "prompt_tokens": int(getattr(usage_obj, "prompt_tokens", 0) or 0),
            "completion_tokens": int(getattr(usage_obj, "completion_tokens", 0) or 0),
        }
        return ProviderResponse(
            text=getattr(message, "content", None) or "",
            tool_calls=calls,
            usage=usage,
            finish_reason=getattr(choice, "finish_reason", None),
        )
