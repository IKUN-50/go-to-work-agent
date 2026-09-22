"""DeepSeek wire-format details stay here, outside the Agent workflow."""

from __future__ import annotations

import logging
from copy import deepcopy
from time import perf_counter, sleep
from typing import Any, Callable

from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError, OpenAI

from .config import LLMSettings
from .llm import LLMError, Messages, event


class DeepSeekProvider:
    def __init__(self, settings: LLMSettings, *, client: Any = None,
                 sleep_fn: Callable[[float], None] = sleep):
        self.settings = settings
        self.events: list[dict] = []
        self._sleep = sleep_fn
        # The SDK's DEBUG logging includes full request messages and exceptions.
        # Keep diagnostics in our metadata events even if OPENAI_LOG is inherited.
        for logger_name in ("openai", "openai._base_client", "httpx", "httpcore"):
            logging.getLogger(logger_name).setLevel(logging.WARNING)
        if client is None:
            if not settings.api_key:
                raise LLMError("missing_api_key", "请在项目 .env 中配置 LLM_API_KEY。", attempts=0)
            # Disable SDK retries so one explicit, measurable retry budget applies.
            try:
                client = OpenAI(api_key=settings.api_key, base_url=settings.base_url,
                                timeout=settings.timeout_seconds, max_retries=0)
            except Exception:
                raise LLMError("client_initialization_failed", "模型客户端初始化失败，请检查配置。",
                               attempts=0) from None
        self._client = client

    def complete(self, messages: Messages, *, json_mode: bool = False) -> str:
        request: dict[str, Any] = {
            "model": self.settings.model,
            "messages": deepcopy(messages),
            "max_tokens": self.settings.max_tokens,
            "extra_body": {"thinking": {"type": "disabled"}},
        }
        if json_mode:
            request["response_format"] = {"type": "json_object"}

        for attempt in range(1, self.settings.transport_retries + 2):
            started = perf_counter()
            try:
                response = self._client.chat.completions.create(**request)
            except (APITimeoutError, APIConnectionError) as error:
                code = "timeout" if isinstance(error, APITimeoutError) else "connection_error"
                failure = LLMError(code, "模型服务连接失败或超时，请稍后重试。",
                                   attempts=attempt, retryable=True)
            except APIStatusError as error:
                status = error.status_code
                retryable = status in {408, 409, 429} or status >= 500
                code, message = {
                    401: ("authentication_failed", "模型 API 密钥无效，请检查配置。"),
                    402: ("insufficient_balance", "模型 API 余额不足。"),
                    403: ("access_denied", "模型 API 拒绝访问，请检查权限。"),
                    429: ("rate_limited", "模型 API 请求过于频繁，请稍后重试。"),
                }.get(status, ("provider_http_error", "模型 API 请求失败，请检查配置或稍后重试。"))
                failure = LLMError(code, message, attempts=attempt, retryable=retryable)
            except APIError:
                failure = LLMError("provider_error", "模型服务调用失败。", attempts=attempt)
            except Exception:
                failure = LLMError("provider_error", "模型服务调用失败。", attempts=attempt)
            else:
                try:
                    content = response.choices[0].message.content
                    if content is not None and not isinstance(content, str):
                        raise TypeError
                except (AttributeError, IndexError, TypeError):
                    self.events.append(event("provider.complete", attempt, False,
                                             started, "invalid_provider_response"))
                    raise LLMError("invalid_provider_response", "模型服务返回了无法识别的响应。",
                                   attempts=attempt) from None
                self.events.append(event("provider.complete", attempt, True, started))
                # Empty text is a format failure that LLMService can repair.
                return content or ""

            self.events.append(event("provider.complete", attempt, False, started, failure.code))
            if not failure.retryable or attempt > self.settings.transport_retries:
                raise failure from None
            self._sleep(0.25)

        raise AssertionError("unreachable")
