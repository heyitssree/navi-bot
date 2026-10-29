# navi/llm/base.py - provider-neutral request/response types and the provider protocol

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

ErrorKind = Literal["rate_limited", "server", "config"]


class LLMError(Exception):
    def __init__(self, kind: ErrorKind, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.kind, self.retry_after = kind, retry_after


@dataclass
class LLMRequest:
    purpose: str            # qa | context_reply | prediction | summary | mod | vibe | template_batch ...
    system: str
    prompt: str
    max_tokens: int = 200   # not sent to Gemini yet (would truncate replies); Bedrock uses it from Phase 7
    temperature: float = 0.8  # current Gemini behaviour (spec default 0.6 would change tone)


@dataclass
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int
    provider: str
    model: str
    latency_ms: int


class LLMProvider(Protocol):
    name: str
    model: str
    key_names: list[str]    # credentials tried in order (Gemini: "free", "paid"); [""] when there is one

    async def generate(self, req: LLMRequest, key: str | None = None) -> LLMResponse: ...
