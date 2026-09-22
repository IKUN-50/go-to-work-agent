"""Provider-independent model calls and Pydantic output validation."""

from __future__ import annotations

import json
from copy import deepcopy
from time import perf_counter
from typing import TYPE_CHECKING, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

if TYPE_CHECKING:
    from .config import LLMSettings

T = TypeVar("T", bound=BaseModel)
Messages = list[dict[str, str]]


def _reject_non_json_number(_: str):
    raise ValueError("JSON must use finite numeric literals.")


class LLMError(Exception):
    """A safe application error; never put a raw provider exception in message."""

    def __init__(self, code: str, message: str, *, attempts: int = 1,
                 retryable: bool = False):
        self.code = code
        self.message = message
        self.attempts = attempts
        self.retryable = retryable
        super().__init__(message)


class Provider(Protocol):
    def complete(self, messages: Messages, *, json_mode: bool = False) -> str:
        """Return text without exposing a vendor response object to callers."""
        ...


def event(operation: str, attempt: int, success: bool,
          started: float, error_code: str | None = None) -> dict:
    """Operational metadata only: no prompt, response, key or exception text."""
    return {"operation": operation, "attempt": attempt, "success": success,
            "duration_ms": round((perf_counter() - started) * 1000, 3),
            "error_code": error_code}


class FakeProvider:
    """Scripted, offline provider. Its in-memory calls support test assertions."""

    def __init__(self, responses: list[str | Exception]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def complete(self, messages: Messages, *, json_mode: bool = False) -> str:
        self.calls.append({"messages": deepcopy(messages), "json_mode": json_mode})
        if not self.responses:
            raise LLMError("fake_exhausted", "离线模型的预设响应已用完。")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class LLMService:
    def __init__(self, provider: Provider, max_repair_attempts: int = 1):
        if type(max_repair_attempts) is not int or not 0 <= max_repair_attempts <= 1:
            raise LLMError("invalid_config", "结构化输出修复次数必须为 0 或 1。")
        self.provider = provider
        self.max_repair_attempts = max_repair_attempts
        self.events: list[dict] = []

    def _complete(self, messages: Messages, *, json_mode: bool) -> str:
        provider_events = getattr(self.provider, "events", [])
        previous_count = len(provider_events)
        try:
            return self.provider.complete(deepcopy(messages), json_mode=json_mode)
        except LLMError:
            raise
        except Exception:
            # Third-party adapters must not expose their raw exceptions either.
            raise LLMError("provider_error", "模型服务调用失败，请检查配置或稍后重试。") from None
        finally:
            self.events.extend(deepcopy(provider_events[previous_count:]))

    def generate(self, messages: Messages) -> str:
        started = perf_counter()
        try:
            content = self._complete(messages, json_mode=False)
            if not isinstance(content, str) or not content.strip():
                raise LLMError("empty_response", "模型没有返回可用文本。")
        except LLMError as error:
            self.events.append(event("generate", error.attempts, False, started, error.code))
            raise
        self.events.append(event("generate", 1, True, started))
        return content

    def generate_structured(self, messages: Messages, schema: type[T]) -> T:
        """Return the project's Pydantic object, with at most one format repair.

        Transport failures stop this operation; only invalid output is repaired.
        Repair prompts contain schema/error categories, never raw failed output.
        """
        contract = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        request = [{"role": "system", "content": (
            "Return one valid json object only, without Markdown fences. "
            "Its fields must satisfy this JSON Schema: " + contract
        )}, *deepcopy(messages)]

        for attempt in range(1, self.max_repair_attempts + 2):
            started = perf_counter()
            try:
                content = self._complete(request, json_mode=True)
            except LLMError as error:
                self.events.append(event("generate_structured", attempt, False,
                                         started, error.code))
                raise

            error_code = "empty_response"
            if isinstance(content, str) and content.strip():
                try:
                    data = json.loads(content, parse_constant=_reject_non_json_number)
                except (ValueError, RecursionError):
                    error_code = "invalid_json"
                else:
                    try:
                        result = schema.model_validate(data)
                    except ValidationError:
                        # str(ValidationError) can contain private input values.
                        error_code = "schema_validation_failed"
                    else:
                        self.events.append(event("generate_structured", attempt,
                                                 True, started))
                        return result

            self.events.append(event("generate_structured", attempt, False,
                                     started, error_code))
            if attempt <= self.max_repair_attempts:
                request.append({"role": "user", "content": (
                    "The previous answer failed validation (" + error_code + "). "
                    "Try again. Return only a complete json object matching the "
                    "JSON Schema above; include all required fields and correct types."
                )})

        raise LLMError("structured_output_invalid",
                       "模型输出在有限修复后仍不符合数据格式，本次任务已停止。",
                       attempts=self.max_repair_attempts + 1)


def build_llm(settings: LLMSettings, *,
              fake_responses: list[str | Exception] | None = None) -> LLMService:
    """Select one small adapter; adding another vendor only changes this boundary."""
    if settings.provider == "fake":
        provider: Provider = FakeProvider(fake_responses or [])
    elif settings.provider == "deepseek":
        from .providers import DeepSeekProvider
        provider = DeepSeekProvider(settings)
    else:
        raise LLMError("unsupported_provider", "当前仅支持 fake 和 deepseek Provider。")
    return LLMService(provider, settings.max_repair_attempts)
