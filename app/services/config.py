"""Explicit project .env loading; process variables take precedence."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values

from .llm import LLMError


@dataclass(frozen=True)
class LLMSettings:
    provider: str = "fake"
    api_key: str = field(default="", repr=False)
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-flash"
    timeout_seconds: float = 30.0
    max_tokens: int = 2048
    transport_retries: int = 1
    max_repair_attempts: int = 1

    def __post_init__(self):
        if self.provider not in {"fake", "deepseek"}:
            raise LLMError("unsupported_provider", "当前仅支持 fake 和 deepseek Provider。")
        if (not math.isfinite(self.timeout_seconds)
                or not 1 <= self.timeout_seconds <= 120
                or type(self.max_tokens) is not int or not 128 <= self.max_tokens <= 8192
                or type(self.transport_retries) is not int or not 0 <= self.transport_retries <= 1
                or type(self.max_repair_attempts) is not int or not 0 <= self.max_repair_attempts <= 1):
            raise LLMError("invalid_config", "模型超时、输出上限或重试次数超出允许范围。")
        if not self.model.strip():
            raise LLMError("invalid_config", "LLM_MODEL 不能为空。")
        try:
            endpoint = urlsplit(self.base_url)
        except ValueError:
            raise LLMError("invalid_config", "LLM_BASE_URL 不是有效的服务地址。") from None
        if (endpoint.scheme != "https" or not endpoint.hostname
                or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment):
            raise LLMError("invalid_config", "LLM_BASE_URL 必须为不含凭据或查询参数的 HTTPS 地址。")

    @classmethod
    def from_env(cls, env_path: Path | str) -> LLMSettings:
        """Read this exact .env only; never search parents or alter os.environ."""
        path = Path(env_path)
        try:
            values = dict(dotenv_values(path, interpolate=False)) if path.is_file() else {}
        except (OSError, UnicodeError):
            raise LLMError("config_read_failed", "无法读取项目 .env，请检查文件权限和 UTF-8 编码。") from None

        def value(name: str, legacy: str = "", default: str = "") -> str:
            # Explicit process values beat file values, including legacy names.
            for source in (os.environ, values):
                for key in (name, legacy):
                    if key and key in source and source[key] is not None:
                        return source[key].strip()
            return default

        try:
            return cls(
                provider=value("LLM_PROVIDER", default="fake").lower(),
                api_key=value("LLM_API_KEY", "DEEPSEEK_API_KEY"),
                base_url=value("LLM_BASE_URL", "DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
                model=value("LLM_MODEL", "DEEPSEEK_MODEL", "deepseek-flash"),
                timeout_seconds=float(value("LLM_TIMEOUT_SECONDS", default="30")),
                max_tokens=int(value("LLM_MAX_TOKENS", default="2048")),
                transport_retries=int(value("LLM_TRANSPORT_RETRIES", default="1")),
                max_repair_attempts=int(value("LLM_MAX_REPAIR_ATTEMPTS", default="1")),
            )
        except (TypeError, ValueError):
            raise LLMError("invalid_config", "模型配置中的数字无效，请检查 .env。") from None
