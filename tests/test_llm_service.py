"""Offline tests: no real credentials or provider requests are used."""

import json
import logging
import os
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError
from pydantic import BaseModel, ConfigDict

from app.services import FakeProvider, LLMError, LLMService, LLMSettings, build_llm
from app.services.providers import DeepSeekProvider


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    answer: int


class StubCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def stub_client(responses):
    return SimpleNamespace(chat=SimpleNamespace(completions=StubCompletions(responses)))


def response(text):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


def status_error(status):
    request = httpx.Request("POST", "https://example.invalid/chat/completions")
    result = httpx.Response(status, request=request)
    return APIStatusError("PRIVATE_TEST_SENTINEL", response=result,
                          body={"secret": "PRIVATE_TEST_SENTINEL"})


class LLMServiceTests(unittest.TestCase):
    def test_returns_pydantic_object_and_copies_messages(self):
        fake = FakeProvider(['{"answer": 42}'])
        llm = LLMService(fake)
        messages = [{"role": "user", "content": "calculate"}]
        result = llm.generate_structured(messages, Answer)
        self.assertIsInstance(result, Answer)
        self.assertEqual(result.answer, 42)
        self.assertEqual(len(messages), 1)
        self.assertTrue(fake.calls[0]["json_mode"])
        self.assertIn('"required": ["answer"]', fake.calls[0]["messages"][0]["content"])

    def test_repairs_json_schema_and_empty_output_once(self):
        for first in ("", "  ", "not json", '{"answer": "42"}', '{"answer": 42, "extra": 1}'):
            with self.subTest(first=first):
                fake = FakeProvider([first, '{"answer": 42}'])
                llm = LLMService(fake)
                self.assertEqual(llm.generate_structured([], Answer).answer, 42)
                self.assertEqual(len(fake.calls), 2)
                self.assertEqual([entry["success"] for entry in llm.events], [False, True])

    def test_format_failure_stops_and_contains_no_raw_content(self):
        fake = FakeProvider(["PRIVATE_TEST_SENTINEL", '{"answer": "PRIVATE_TEST_SENTINEL"}'])
        llm = LLMService(fake)
        with self.assertRaises(LLMError) as caught:
            llm.generate_structured([], Answer)
        self.assertEqual(caught.exception.code, "structured_output_invalid")
        self.assertEqual(caught.exception.attempts, 2)
        self.assertEqual(len(fake.calls), 2)
        self.assertNotIn("PRIVATE_TEST_SENTINEL", str(caught.exception))
        self.assertNotIn("PRIVATE_TEST_SENTINEL", json.dumps(llm.events))
        self.assertNotIn("PRIVATE_TEST_SENTINEL", json.dumps(fake.calls[1]))

    def test_oversized_integer_and_non_json_numbers_use_bounded_repair(self):
        for invalid in ('{"answer": ' + "1" * 5000 + "}", '{"answer": NaN}'):
            with self.subTest(length=len(invalid)):
                fake = FakeProvider([invalid, '{"answer": 42}'])
                llm = LLMService(fake)
                self.assertEqual(llm.generate_structured([], Answer).answer, 42)
                self.assertEqual(llm.events[0]["error_code"], "invalid_json")


    def test_transport_failure_is_not_repaired_as_json(self):
        failure = LLMError("connection_error", "safe", attempts=2, retryable=True)
        fake = FakeProvider([failure, '{"answer": 42}'])
        llm = LLMService(fake)
        with self.assertRaises(LLMError) as caught:
            llm.generate_structured([], Answer)
        self.assertIs(caught.exception, failure)
        self.assertEqual(len(fake.calls), 1)

    def test_unknown_adapter_exception_is_sanitized(self):
        llm = LLMService(FakeProvider([RuntimeError("PRIVATE_TEST_SENTINEL")]))
        with self.assertRaises(LLMError) as caught:
            llm.generate([])
        self.assertEqual(caught.exception.code, "provider_error")
        self.assertNotIn("PRIVATE_TEST_SENTINEL", str(caught.exception))

    def test_plain_text_and_empty_text(self):
        self.assertEqual(LLMService(FakeProvider(["hello"])).generate([]), "hello")
        with self.assertRaises(LLMError) as caught:
            LLMService(FakeProvider([""])).generate([])
        self.assertEqual(caught.exception.code, "empty_response")

    def test_repairs_can_be_disabled_and_are_bounded(self):
        fake = FakeProvider(["bad", '{"answer": 42}'])
        with self.assertRaises(LLMError):
            LLMService(fake, max_repair_attempts=0).generate_structured([], Answer)
        self.assertEqual(len(fake.calls), 1)
        for invalid in (-1, 2, True, 0.5):
            with self.assertRaises(LLMError):
                LLMService(fake, max_repair_attempts=invalid)

    def test_events_have_only_safe_metadata(self):
        llm = LLMService(FakeProvider(["hello"]))
        llm.generate([{"role": "user", "content": "PRIVATE_TEST_SENTINEL"}])
        self.assertEqual(set(llm.events[0]),
                         {"operation", "attempt", "success", "duration_ms", "error_code"})
        self.assertNotIn("PRIVATE_TEST_SENTINEL", json.dumps(llm.events))


class DeepSeekProviderTests(unittest.TestCase):
    def test_maps_json_mode_thinking_and_extracts_text(self):
        client = stub_client([response('{"answer": 42}')])
        provider = DeepSeekProvider(LLMSettings(provider="deepseek"), client=client)
        llm = LLMService(provider)
        self.assertEqual(llm.generate_structured([], Answer).answer, 42)
        request = client.chat.completions.calls[0]
        self.assertEqual(request["response_format"], {"type": "json_object"})
        self.assertEqual(request["extra_body"], {"thinking": {"type": "disabled"}})
        self.assertEqual(request["model"], "deepseek-flash")
        self.assertEqual(request["max_tokens"], 2048)
        self.assertEqual([entry["operation"] for entry in llm.events],
                         ["provider.complete", "generate_structured"])

    def test_sdk_retry_disabled_and_timeout_configured(self):
        with patch("app.services.providers.OpenAI", return_value=stub_client([])) as sdk:
            DeepSeekProvider(LLMSettings(provider="deepseek", api_key="TEST_ONLY"))
        self.assertEqual(sdk.call_args.kwargs["max_retries"], 0)
        self.assertEqual(sdk.call_args.kwargs["timeout"], 30)

    def test_transport_retry_succeeds_once(self):
        request = httpx.Request("POST", "https://example.invalid")
        errors = [APIConnectionError(request=request), APITimeoutError(request=request),
                  status_error(429), status_error(503)]
        for failure in errors:
            with self.subTest(failure=type(failure).__name__):
                client = stub_client([failure, response("ok")])
                sleeps = []
                provider = DeepSeekProvider(LLMSettings(provider="deepseek"), client=client,
                                            sleep_fn=sleeps.append)
                self.assertEqual(provider.complete([]), "ok")
                self.assertEqual(len(client.chat.completions.calls), 2)
                self.assertEqual(sleeps, [0.25])

    def test_auth_balance_bad_request_do_not_retry(self):
        for status in (400, 401, 402, 403):
            with self.subTest(status=status):
                client = stub_client([status_error(status)])
                provider = DeepSeekProvider(LLMSettings(provider="deepseek"), client=client)
                with self.assertRaises(LLMError) as caught:
                    provider.complete([])
                self.assertEqual(len(client.chat.completions.calls), 1)
                self.assertFalse(caught.exception.retryable)
                self.assertNotIn("PRIVATE_TEST_SENTINEL", str(caught.exception))
                self.assertNotIn("PRIVATE_TEST_SENTINEL", json.dumps(provider.events))

    def test_exhausted_transport_retry_does_not_start_format_repair(self):
        client = stub_client([status_error(503), status_error(503), response('{"answer": 42}')])
        provider = DeepSeekProvider(LLMSettings(provider="deepseek"), client=client,
                                    sleep_fn=lambda _: None)
        llm = LLMService(provider)
        with self.assertRaises(LLMError) as caught:
            llm.generate_structured([], Answer)
        self.assertEqual(caught.exception.attempts, 2)
        self.assertEqual(len(client.chat.completions.calls), 2)

    def test_empty_sdk_content_uses_format_repair(self):
        client = stub_client([response(None), response('{"answer": 42}')])
        llm = LLMService(DeepSeekProvider(LLMSettings(), client=client))
        self.assertEqual(llm.generate_structured([], Answer).answer, 42)
        self.assertEqual(len(client.chat.completions.calls), 2)

    def test_no_retry_budget_means_exactly_one_provider_request(self):
        client = stub_client([status_error(503), response("must not be used")])
        settings = LLMSettings(provider="deepseek", transport_retries=0)
        provider = DeepSeekProvider(settings, client=client)
        with self.assertRaises(LLMError) as caught:
            provider.complete([])
        self.assertEqual(caught.exception.attempts, 1)
        self.assertEqual(len(client.chat.completions.calls), 1)

    def test_malformed_sdk_response_has_explicit_safe_error(self):
        client = stub_client([SimpleNamespace(choices=[])])
        provider = DeepSeekProvider(LLMSettings(), client=client)
        with self.assertRaises(LLMError) as caught:
            provider.complete([])
        self.assertEqual(caught.exception.code, "invalid_provider_response")

    def test_missing_key_fails_before_sdk_creation(self):
        with patch("app.services.providers.OpenAI") as sdk:
            with self.assertRaises(LLMError) as caught:
                DeepSeekProvider(LLMSettings(provider="deepseek"))
        self.assertEqual(caught.exception.code, "missing_api_key")
        sdk.assert_not_called()

    def test_sdk_debug_request_logging_is_disabled(self):
        logger = logging.getLogger("openai._base_client")
        previous_level = logger.level
        try:
            logger.setLevel(logging.DEBUG)
            DeepSeekProvider(LLMSettings(), client=stub_client([]))
            self.assertFalse(logger.isEnabledFor(logging.DEBUG))
        finally:
            logger.setLevel(previous_level)


class LLMSettingsTests(unittest.TestCase):
    def test_missing_env_defaults_to_fake_without_reading_parents(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = LLMSettings.from_env(Path(__file__).parent / "missing.env")
        self.assertEqual(settings.provider, "fake")
        self.assertEqual(settings.api_key, "")
        self.assertEqual(build_llm(settings, fake_responses=["ready"]).generate([]), "ready")

    def test_explicit_file_legacy_environment_priority_and_hidden_key(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / ".env"
            path.write_text("LLM_API_KEY=FILE_TEST_ONLY\nLLM_MODEL=file-model\n", encoding="utf-8")
            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "ENV_TEST_ONLY",
                                        "DEEPSEEK_MODEL": "environment-model"}, clear=True):
                before = dict(os.environ)
                settings = LLMSettings.from_env(path)
                self.assertEqual(dict(os.environ), before)
            self.assertEqual(settings.api_key, "ENV_TEST_ONLY")
            self.assertEqual(settings.model, "environment-model")
            self.assertNotIn("ENV_TEST_ONLY", repr(settings))

    def test_explicit_empty_environment_key_overrides_file(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / ".env"
            path.write_text("LLM_API_KEY=FILE_TEST_ONLY\n", encoding="utf-8")
            with patch.dict(os.environ, {"LLM_API_KEY": ""}, clear=True):
                self.assertEqual(LLMSettings.from_env(path).api_key, "")

    def test_invalid_config_is_safe_and_bounded(self):
        for name, value in (("LLM_TIMEOUT_SECONDS", "nan"), ("LLM_MAX_TOKENS", "999999"),
                            ("LLM_TRANSPORT_RETRIES", "2"), ("LLM_MAX_REPAIR_ATTEMPTS", "2"),
                            ("LLM_MAX_TOKENS", "PRIVATE_TEST_SENTINEL"),
                            ("LLM_BASE_URL", "https://user:PRIVATE_TEST_SENTINEL@example.invalid")):
            with self.subTest(name=name, value=value):
                with patch.dict(os.environ, {name: value}, clear=True):
                    with self.assertRaises(LLMError) as caught:
                        LLMSettings.from_env(Path(__file__).parent / "missing.env")
                self.assertNotIn("PRIVATE_TEST_SENTINEL", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
