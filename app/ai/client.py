from __future__ import annotations

import base64
import json
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

import jsonschema
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    InternalServerError,
    RateLimitError,
)
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from app.ai.errors import ModelUnavailable, OutputParseError, RateLimitExhausted
from app.ai.models import ModelRole, resolve_model
from app.config import Settings, get_settings
from app.logging import get_logger

log = get_logger(__name__)

# Callers set these context vars before calling agents so the client can
# attribute token usage to the right tenant/document without changing agent
# signatures. Set to None to skip logging (e.g. in tests).
llm_log_tenant_id: ContextVar[uuid.UUID | None] = ContextVar("llm_log_tenant_id", default=None)
llm_log_document_id: ContextVar[uuid.UUID | None] = ContextVar("llm_log_document_id", default=None)


@dataclass
class ImageInput:
    data: bytes
    mime: str


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@dataclass
class AIResponse:
    content: Any
    model: str
    usage: TokenUsage
    raw: dict = field(default_factory=dict)


_RETRYABLE_EXC = (RateLimitError, InternalServerError, APIConnectionError, APITimeoutError)


async def _log_usage(role: ModelRole, model: str, usage: TokenUsage) -> None:
    tenant_id = llm_log_tenant_id.get()
    if tenant_id is None:
        return
    document_id = llm_log_document_id.get()
    try:
        from app.db.models.llm_call_log import LLMCallLog
        from app.db.session import SessionLocal

        async with SessionLocal() as session:
            row = LLMCallLog(
                tenant_id=tenant_id,
                document_id=document_id,
                role=role.value,
                model=model,
                prompt_tokens=usage.input_tokens,
                completion_tokens=usage.output_tokens,
                total_tokens=usage.total_tokens,
            )
            session.add(row)
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning("llm_usage_log_failed", error=str(exc))


def _usage_of(resp: Any) -> TokenUsage:
    usage = getattr(resp, "usage", None)
    if usage is None:
        return TokenUsage()
    return TokenUsage(
        input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
        total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
    )


class OpenRouterClient:
    """Async AI client — supports OpenRouter and Ollama via the openai SDK.

    Provider is selected by settings.ai_provider:
      "openrouter" (default) — uses openrouter_base_url + openrouter_api_key
      "ollama"               — uses ollama_base_url; gemma4 handles vision OCR too

    Both providers expose an OpenAI-compatible chat completions endpoint, so
    the same SDK and request structure works for both. The only difference is
    the base URL, API key, and timeout.

    For Ollama, a separate OpenRouter client (_or_client) is kept alive for
    VISION_OCR calls because most local models don't handle image inputs.
    """

    def __init__(self, settings: Settings | None = None, max_attempts: int = 5) -> None:
        self._settings = settings or get_settings()
        self._max_attempts = max_attempts
        self._is_ollama = self._settings.ai_provider == "ollama"

        if self._is_ollama:
            self._client = AsyncOpenAI(
                api_key="ollama",  # Ollama ignores the key but SDK requires a non-empty value
                base_url=self._settings.ollama_base_url,
                timeout=self._settings.ollama_timeout_s,
            )
            # Separate OpenRouter client kept for VISION_OCR calls
            self._or_client = AsyncOpenAI(
                api_key=self._settings.openrouter_api_key or "missing",
                base_url=self._settings.openrouter_base_url,
                timeout=self._settings.openrouter_timeout_s,
                default_headers={
                    "HTTP-Referer": "https://github.com/medx/medx",
                    "X-Title": self._settings.openrouter_app_title,
                },
            )
        else:
            self._client = AsyncOpenAI(
                api_key=self._settings.openrouter_api_key or "missing",
                base_url=self._settings.openrouter_base_url,
                timeout=self._settings.openrouter_timeout_s,
                default_headers={
                    "HTTP-Referer": "https://github.com/medx/medx",
                    "X-Title": self._settings.openrouter_app_title,
                },
            )
            self._or_client = self._client  # same client for OCR

    async def aclose(self) -> None:
        await self._client.close()
        if self._is_ollama:
            await self._or_client.close()

    async def complete_text(
        self,
        *,
        role: ModelRole,
        system: str,
        user: str,
        images: list[ImageInput] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        max_attempts: int | None = None,
    ) -> AIResponse:
        """Call the LLM and return the raw text response.

        Used for free-text generation (summarization, chat answers).
        Token usage is logged via LLMCallLog if context vars are set.
        """
        model = resolve_model(role, self._settings)
        underlying = self._client
        messages = self._build_messages(system, user, images)
        resp = await self._call(
            underlying,
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            _max_attempts=max_attempts,
        )
        text = (resp.choices[0].message.content or "") if resp.choices else ""
        ai_resp = AIResponse(
            content=text,
            model=model,
            usage=_usage_of(resp),
            raw=resp.model_dump() if hasattr(resp, "model_dump") else {},
        )
        await _log_usage(role, model, ai_resp.usage)
        return ai_resp

    async def complete_json(
        self,
        *,
        role: ModelRole,
        system: str,
        user: str,
        schema: dict | None = None,
        images: list[ImageInput] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> AIResponse:
        """Call the LLM and return a validated JSON payload.

        Enforces json_object response format and validates against `schema` if
        provided. On a parse or validation failure, sends a repair prompt and
        retries once before raising OutputParseError.

        Used for all structured extraction calls where the output must conform
        to a specific JSON schema (classify, extract_*, patient_info).
        """
        model = resolve_model(role, self._settings)
        underlying = self._or_client if role == ModelRole.VISION_OCR else self._client
        # Ollama supports json_object mode; include it for both providers
        system_with_json = system + "\n\nReply with JSON only. Do not include commentary or markdown fences."
        messages = self._build_messages(system_with_json, user, images)

        resp = await self._call(
            underlying,
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        raw_text = (resp.choices[0].message.content or "{}") if resp.choices else "{}"

        parsed, err = _try_parse(raw_text, schema)
        if err is not None:
            log.warning(
                "json_parse_retry", role=role.value, model=model, error=str(err)
            )
            repair = [
                *messages,
                {"role": "assistant", "content": raw_text},
                {
                    "role": "user",
                    "content": (
                        "Your previous reply was not valid JSON matching the required schema. "
                        f"Error: {err}. Reply with valid JSON only."
                    ),
                },
            ]
            resp = await self._call(
                underlying,
                model=model,
                messages=repair,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            raw_text = (resp.choices[0].message.content or "{}") if resp.choices else "{}"
            parsed, err2 = _try_parse(raw_text, schema)
            if err2 is not None:
                raise OutputParseError(
                    f"Model returned invalid JSON after repair: {err2}", raw_text=raw_text
                )

        ai_resp = AIResponse(
            content=parsed,
            model=model,
            usage=_usage_of(resp),
            raw=resp.model_dump() if hasattr(resp, "model_dump") else {},
        )
        await _log_usage(role, model, ai_resp.usage)
        return ai_resp

    def _build_messages(
        self, system: str, user: str, images: list[ImageInput] | None
    ) -> list[dict]:
        if not images:
            return [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
        content: list[dict] = [{"type": "text", "text": user}]
        for img in images:
            b64 = base64.b64encode(img.data).decode()
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{img.mime};base64,{b64}"},
                }
            )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": content},
        ]

    async def _call(
        self,
        client: AsyncOpenAI | None = None,
        _max_attempts: int | None = None,
        **kwargs: Any,
    ) -> Any:
        c = client or self._client
        attempts = _max_attempts if _max_attempts is not None else self._max_attempts
        model = kwargs.get("model", "?")
        log.info("llm_call_start", model=model, input_chars=sum(len(m.get("content", "") if isinstance(m.get("content"), str) else "") for m in kwargs.get("messages", [])))
        t0 = time.monotonic()
        try:
            async for attempt in AsyncRetrying(
                retry=retry_if_exception_type(_RETRYABLE_EXC),
                wait=wait_random_exponential(multiplier=1, max=30),
                stop=stop_after_attempt(attempts),
                reraise=True,
            ):
                with attempt:
                    try:
                        resp = await c.chat.completions.create(**kwargs)
                        log.info("llm_call_done", model=model, elapsed_s=round(time.monotonic() - t0, 1), tokens=getattr(getattr(resp, "usage", None), "total_tokens", "?"))
                        return resp
                    except APIStatusError as exc:
                        code = getattr(exc, "status_code", None)
                        if code == 402:
                            raise RateLimitExhausted(
                                f"OpenRouter returned 402 (budget exhausted): {exc}"
                            ) from exc
                        if code == 404:
                            raise ModelUnavailable(
                                f"Model not found at provider: {exc}"
                            ) from exc
                        # Some providers reject system messages with 400.
                        # Retry once with system merged into user content.
                        if code == 400 and "messages" in kwargs:
                            msgs = kwargs["messages"]
                            if msgs and msgs[0].get("role") == "system":
                                merged = [
                                    {
                                        "role": "user",
                                        "content": msgs[0]["content"]
                                        + "\n\n"
                                        + (msgs[1]["content"] if len(msgs) > 1 else ""),
                                    }
                                ]
                                patched = {**kwargs, "messages": merged}
                                return await c.chat.completions.create(**patched)
                        raise
        except RateLimitError as exc:
            raise RateLimitExhausted(
                f"Rate-limited after {attempts} attempts: {exc}"
            ) from exc
        raise AssertionError("unreachable: AsyncRetrying exited without returning or raising")


def _try_parse(raw: str, schema: dict | None) -> tuple[Any, Exception | None]:
    text = raw.strip()
    # Strip markdown fences the model sometimes wraps JSON in
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(
            l for l in lines if not l.startswith("```")
        ).strip()
    # If the model appended extra text after the closing brace/bracket,
    # find the last valid JSON boundary and truncate there.
    if text and text[0] in ("{", "["):
        closer = "}" if text[0] == "{" else "]"
        idx = text.rfind(closer)
        if idx != -1:
            text = text[: idx + 1]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, exc
    if schema is not None:
        try:
            jsonschema.validate(parsed, schema)
        except jsonschema.ValidationError as exc:
            return None, exc
    return parsed, None


_client_singleton: OpenRouterClient | None = None


def get_ai_client() -> OpenRouterClient:
    global _client_singleton
    if _client_singleton is None:
        _client_singleton = OpenRouterClient()
    return _client_singleton


def set_ai_client(client: OpenRouterClient | None) -> None:
    """Test hook: override or clear the singleton."""
    global _client_singleton
    _client_singleton = client
