"""Offline checks for data provenance, boundaries and predictable tool failures."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from pydantic import ValidationError

from app.schemas.profile import ProfileData
from app.schemas.tool import ReadProfileInput, SearchItem, SearchJobsInput, ToolResult
from app.tools.errors import ToolFailure
from app.tools.profile_reader import MAX_LOCAL_BYTES, read_allowed_json
from app.tools.registry import ToolRegistry
from app.tools.web_search import MAX_RESPONSE_BYTES, RemotiveSearch, _fetch_snapshot, is_public_result_url, matches_query, parse_remotive_snapshot, search_remotive

ROOT = Path(__file__).resolve().parents[1]


class CareerToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tools = ToolRegistry()

    def test_definitions_are_vendor_neutral(self) -> None:
        definitions = self.tools.definitions()
        self.assertEqual([item.name for item in definitions], ["read_profile", "search_jobs"])
        self.assertFalse(definitions[0].input_schema["additionalProperties"])
        self.assertEqual(definitions[1].input_schema["properties"]["limit"]["maximum"], 5)

    def test_inputs_reject_unknown_fields_private_paths_and_bad_limits(self) -> None:
        for arguments in ({"profile_name": ".env"}, {"profile_name": "../profile.json"}, {"filename": "profile.json"}):
            with self.subTest(arguments=arguments), self.assertRaises(ValidationError):
                ReadProfileInput.model_validate(arguments)
        for arguments in ({"query": "  "}, {"query": "x" * 301}, {"query": "Python", "limit": 6}, {"query": "Python", "limit": True}, {"query": "Python", "limit": "3"}, {"query": "Python", "source": "web"}):
            with self.subTest(arguments=arguments), self.assertRaises(ValidationError):
                SearchJobsInput.model_validate(arguments)
        self.assertEqual(SearchJobsInput(query="  Python  ").query, "Python")

    def test_profile_is_explicitly_synthetic_and_structured(self) -> None:
        result = self.tools.execute("read_profile", {})
        self.assertTrue(result.success)
        self.assertTrue(result.data["sample"])
        self.assertEqual(result.data["skills"]["Pydantic"], "learning")
        self.assertIn("Synthetic", result.data["notice"])

    def test_search_samples_rank_and_preserve_provenance(self) -> None:
        result = self.tools.execute("search_jobs", {"query": "Pydantic", "limit": 1})
        self.assertTrue(result.success)
        self.assertEqual(result.data["source_mode"], "sample")
        self.assertEqual(len(result.data["items"]), 1)
        self.assertEqual(result.data["items"][0]["source_kind"], "synthetic")
        self.assertIn("not live vacancies", result.data["warnings"][0])

    def test_non_matching_query_does_not_return_fixed_results(self) -> None:
        for query in ("zzzzzzzzzz", "I want to be a chef"):
            with self.subTest(query=query):
                result = self.tools.execute("search_jobs", {"query": query})
                self.assertTrue(result.success)
                self.assertEqual(result.data["items"], [])
                self.assertIn("No matching results", result.data["warnings"][-1])

    def test_custom_profile_can_declare_it_is_not_a_sample(self) -> None:
        data = json.loads((ROOT / "data" / "profile.json").read_text(encoding="utf-8"))
        data["sample"] = False
        self.assertFalse(ProfileData.model_validate(data).sample)

    def test_unknown_tool_and_arguments_are_safe(self) -> None:
        secret = "private-secret-must-not-appear"
        unknown = self.tools.execute(secret, {})
        invalid = self.tools.execute("read_profile", {"profile_name": secret})
        self.assertEqual(unknown.error.code, "UNKNOWN_TOOL")
        self.assertEqual(invalid.error.code, "INVALID_TOOL_INPUT")
        self.assertNotIn(secret, unknown.model_dump_json() + invalid.model_dump_json())
        with self.assertRaisesRegex(ValueError, "schema validation") as caught:
            self.tools.validate_arguments("read_profile", {"profile_name": secret})
        self.assertNotIn(secret, str(caught.exception))

    def test_missing_file_is_reported_without_leaking_path(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            result = ToolRegistry(data_dir=Path(temporary)).execute("read_profile", {})
        self.assertEqual(result.error.code, "DATA_NOT_FOUND")
        self.assertFalse(result.error.retryable)
        self.assertNotIn(temporary, result.model_dump_json())

    def test_file_allowlist_rejects_even_existing_private_file(self) -> None:
        with self.assertRaises(ToolFailure) as caught:
            read_allowed_json(ROOT, ".env")
        self.assertEqual(caught.exception.code, "FILE_NOT_ALLOWED")

    def test_size_limit_and_bad_json_are_safe(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            path = Path(temporary) / "profile.json"
            path.write_bytes(b"x" * (MAX_LOCAL_BYTES + 1))
            tools = ToolRegistry(data_dir=Path(temporary))
            self.assertEqual(tools.execute("read_profile", {}).error.code, "DATA_TOO_LARGE")
            path.write_text('{"raw-secret":', encoding="utf-8")
            result = tools.execute("read_profile", {})
            self.assertEqual(result.error.code, "DATA_INVALID")
            self.assertNotIn("raw-secret", result.model_dump_json())

    def test_invalid_profile_schema_is_contained(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            (Path(temporary) / "profile.json").write_text(json.dumps({"sample": False, "api_key": "private-secret"}), encoding="utf-8")
            result = ToolRegistry(data_dir=Path(temporary)).execute("read_profile", {})
        self.assertEqual(result.error.code, "INVALID_TOOL_OUTPUT")
        self.assertNotIn("private-secret", result.model_dump_json())

    def test_web_backend_success_preserves_web_source(self) -> None:
        backend = Mock(return_value=[SearchItem(title="Python Developer", url="https://remotive.com/remote-jobs/software-development/python-developer-1", snippet="Python application development", source_kind="public_job_listing")])
        result = ToolRegistry(search_mode="web", search_backend=backend).execute("search_jobs", {"query": "Python", "limit": 1})
        backend.assert_called_once_with("Python", 1)
        self.assertTrue(result.success)
        self.assertEqual(result.data["source_mode"], "web")
        self.assertIn("not been verified", " ".join(result.data["warnings"]))

    def test_web_failure_never_falls_back_to_sample_or_retries_inside_tool(self) -> None:
        backend = Mock(side_effect=TimeoutError("raw-secret"))
        result = ToolRegistry(search_mode="web", search_backend=backend).execute("search_jobs", {"query": "Python"})
        self.assertFalse(result.success)
        self.assertIsNone(result.data)
        self.assertTrue(result.error.retryable)
        self.assertNotIn("raw-secret", result.model_dump_json())
        backend.assert_called_once()

    def test_unknown_backend_exception_is_safe(self) -> None:
        result = ToolRegistry(search_mode="web", search_backend=Mock(side_effect=RuntimeError("raw-secret"))).execute("search_jobs", {"query": "Python"})
        self.assertEqual(result.error.code, "TOOL_ERROR")
        self.assertNotIn("raw-secret", result.model_dump_json())

    def test_web_backend_output_is_validated(self) -> None:
        for output in ([{"title": "bad", "private": "raw-secret"}], [SearchItem(title="Wrong provenance", url="https://example.org/jobs/1", snippet="", source_kind="synthetic")], [SearchItem(title="Private URL", url="http://127.0.0.1/", snippet="", source_kind="public_job_listing")]):
            with self.subTest(output=output):
                result = ToolRegistry(search_mode="web", search_backend=Mock(return_value=output)).execute("search_jobs", {"query": "Python"})
                self.assertEqual(result.error.code, "INVALID_TOOL_OUTPUT")
                self.assertNotIn("raw-secret", result.model_dump_json())

    def test_web_empty_result_is_honest(self) -> None:
        result = ToolRegistry(search_mode="web", search_backend=Mock(return_value=[])).execute("search_jobs", {"query": "Python"})
        self.assertTrue(result.success)
        self.assertEqual(result.data["source_mode"], "web")
        self.assertEqual(result.data["items"], [])
        self.assertIn("no alternative source", result.data["warnings"][-1])

    def test_irrelevant_web_output_is_filtered_even_from_injected_backend(self) -> None:
        backend = Mock(return_value=[SearchItem(
            title="写真館 Photography Studio",
            url="https://remotive.com/remote-jobs/design/photography-1",
            snippet="Portrait photos, a photo studio and jobs.",
            source_kind="public_job_listing",
        )])
        result = ToolRegistry(search_mode="web", search_backend=backend).execute("search_jobs", {"query": "Junior AI Agent Engineer Python jobs"})
        self.assertTrue(result.success)
        self.assertEqual(result.data["items"], [])

    def test_result_envelope_rejects_contradictory_success(self) -> None:
        with self.assertRaises(ValidationError):
            ToolResult(tool="search_jobs", success=True)


def source_job(**changes: object) -> dict[str, object]:
    job = {
        "id": 1, "title": "Senior AI Engineer", "company_name": "Example source company",
        "url": "https://remotive.com/remote-jobs/software-development/ai-engineer-1",
        "description": "<p>Build AI agents with Python. Mentor junior colleagues.</p>",
        "publication_date": "2026-09-18T12:00:00", "candidate_required_location": "Worldwide",
    }
    job.update(changes)
    return job


def source_payload(*jobs: dict[str, object]) -> bytes:
    return json.dumps({"jobs": list(jobs)}).encode("utf-8")


class RemotiveSearchTests(unittest.TestCase):
    def test_verified_source_shape_matches_meaningful_query(self) -> None:
        raw = source_payload(source_job(), source_job(id=2, title="Photography Studio", description="A Japanese photo studio with jobs."))
        results = parse_remotive_snapshot(raw, "AI Engineer Python", 3)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "Senior AI Engineer")
        self.assertIn("Source: Remotive", results[0].snippet)
        self.assertIn("Published: 2026-09-18", results[0].snippet)
        self.assertEqual(results[0].source_kind, "public_job_listing")
        self.assertNotIn("<p>", results[0].snippet)

    def test_junior_query_does_not_match_senior_mentoring_juniors(self) -> None:
        raw = source_payload(source_job())
        self.assertEqual(parse_remotive_snapshot(raw, "Junior AI Agent Engineer Python jobs", 3), [])
        junior = source_payload(source_job(title="Junior AI Engineer"))
        self.assertEqual(len(parse_remotive_snapshot(junior, "Junior AI Agent Engineer Python jobs", 3)), 1)

    def test_generic_terms_wrong_role_and_wrong_technical_terms_do_not_match(self) -> None:
        cases = [
            ("Photography Studio", "A photo studio with jobs.", "Junior AI Agent Engineer Python jobs"),
            ("Customer Support", "Collaborate with AI engineers who write Python.", "AI Engineer Python"),
            ("Senior Java Engineer", "Java backend jobs.", "AI Engineer Python"),
            ("Senior AI Engineer", "Build Python agents.", "a jobs and roles"),
        ]
        for title, text, query in cases:
            with self.subTest(title=title, query=query):
                self.assertFalse(matches_query(title, text, query))

    def test_using_ai_tools_does_not_make_a_rails_role_an_ai_role(self) -> None:
        self.assertFalse(matches_query("Tech Lead Full-Stack Rails Engineer", "Build AI-driven products with Python and LLM tools.", "AI Engineer"))
        self.assertTrue(matches_query("Artificial Intelligence Engineer", "Build AI agents with Python.", "AI Engineer Python"))
        self.assertTrue(matches_query("Machine Learning Engineer", "Build ML applications with Python.", "ML Engineer Python"))

    def test_duplicate_and_non_remotive_links_are_not_returned(self) -> None:
        raw = source_payload(source_job(), source_job(), source_job(id=2, url="https://example.org/not-a-job"), source_job(id=3, url="http://127.0.0.1/job"))
        self.assertEqual(len(parse_remotive_snapshot(raw, "AI Engineer", 5)), 1)

    def test_invalid_source_schema_and_size_fail_safely(self) -> None:
        cases = [(b"<html>blocked</html>", "SEARCH_FORMAT_INVALID"), (b'{"jobs":[{"secret":"raw-secret"}]}', "SEARCH_FORMAT_INVALID"), (b"x" * (MAX_RESPONSE_BYTES + 1), "SEARCH_TOO_LARGE")]
        for payload, code in cases:
            with self.subTest(code=code), self.assertRaises(ToolFailure) as caught:
                parse_remotive_snapshot(payload, "AI Engineer", 3)
            self.assertEqual(caught.exception.code, code)
            self.assertNotIn("raw-secret", str(caught.exception))

    def test_public_url_filter(self) -> None:
        for url in ("file:///etc/passwd", "http://localhost/a", "http://10.1.1.1/a", "http://127.1/a", "http://[::1]/", "https://user:password@example.org/", "https://example.org:abc/", "https://example.org:8443/", "https://test.internal/", "https://exa\nmple.org/"):
            with self.subTest(url=url):
                self.assertFalse(is_public_result_url(url))
        self.assertTrue(is_public_result_url("https://remotive.com/remote-jobs/software-development/ai-engineer-1"))

    def test_rate_limit_does_not_automatically_retry_or_leak_body(self) -> None:
        opener = Mock()
        opener.open.side_effect = HTTPError("https://example.org/private", 429, "raw-secret", {}, None)
        with patch("app.tools.web_search.build_opener", return_value=opener):
            with self.assertRaises(ToolFailure) as caught:
                _fetch_snapshot()
        self.assertEqual(caught.exception.code, "SEARCH_RATE_LIMITED")
        self.assertFalse(caught.exception.retryable)
        self.assertNotIn("raw-secret", str(caught.exception))

    def test_http_500_is_retryable_and_safe(self) -> None:
        opener = Mock()
        opener.open.side_effect = HTTPError("https://example.org/private", 500, "raw-secret", {}, None)
        with patch("app.tools.web_search.build_opener", return_value=opener):
            with self.assertRaises(ToolFailure) as caught:
                _fetch_snapshot()
        self.assertTrue(caught.exception.retryable)
        self.assertNotIn("raw-secret", str(caught.exception))

    def test_request_has_fixed_endpoint_no_query_timeout_and_bounded_read(self) -> None:
        response = Mock()
        response.read.return_value = source_payload()
        context = Mock()
        context.__enter__ = Mock(return_value=response)
        context.__exit__ = Mock(return_value=False)
        opener = Mock()
        opener.open.return_value = context
        with patch("app.tools.web_search.build_opener", return_value=opener):
            self.assertEqual(_fetch_snapshot(), source_payload())
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://remotive.com/api/remote-jobs")
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 10)
        response.read.assert_called_once_with(MAX_RESPONSE_BYTES + 1)

    def test_cache_reuses_public_snapshot_without_storing_goal(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            cache = Path(temporary) / "remotive_jobs_cache.json"
            search = RemotiveSearch(cache)
            with patch("app.tools.web_search._fetch_snapshot", return_value=source_payload(source_job())) as fetch:
                self.assertEqual(len(search("AI Engineer", 3)), 1)
                self.assertIn("refreshed", search.status_note)
                self.assertEqual(search("Junior AI Agent Engineer Python jobs", 3), [])
                self.assertIn("cache status: hit", search.status_note)
                fetch.assert_called_once()
            self.assertNotIn("Junior AI Agent Engineer Python jobs", cache.read_text(encoding="utf-8"))
            self.assertEqual(list(Path(temporary).glob("*.tmp")), [])

    def test_stale_cache_does_not_hide_provider_failure(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            cache = Path(temporary) / "remotive_jobs_cache.json"
            cache.write_bytes(source_payload(source_job()))
            os.utime(cache, (1, 1))
            with patch("app.tools.web_search._fetch_snapshot", side_effect=ToolFailure("SEARCH_TIMEOUT", "Safe timeout.", True)):
                with self.assertRaises(ToolFailure) as caught:
                    search_remotive("AI Engineer", 3, cache_path=cache)
            self.assertEqual(caught.exception.code, "SEARCH_TIMEOUT")

    def test_failed_request_cooldown_stops_immediate_extra_network_call(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            cache = Path(temporary) / "remotive_jobs_cache.json"
            with patch("app.tools.web_search._fetch_snapshot", side_effect=ToolFailure("SEARCH_TIMEOUT", "Safe timeout.", True)) as fetch:
                with self.assertRaises(ToolFailure):
                    search_remotive("AI Engineer", 3, cache_path=cache)
                with self.assertRaises(ToolFailure) as caught:
                    search_remotive("AI Engineer", 3, cache_path=cache)
                self.assertEqual(caught.exception.code, "SEARCH_COOLDOWN")
                self.assertFalse(caught.exception.retryable)
                fetch.assert_called_once()

    def test_cache_outside_repository_is_rejected_before_network(self) -> None:
        with patch("app.tools.web_search._fetch_snapshot") as fetch:
            with self.assertRaises(ToolFailure) as caught:
                search_remotive("AI Engineer", 3, cache_path=ROOT.parent / "remotive_jobs_cache.json")
        self.assertEqual(caught.exception.code, "SEARCH_CACHE_BLOCKED")
        fetch.assert_not_called()

    def test_link_resolution_outside_repository_is_rejected_before_network(self) -> None:
        cache = ROOT / "runtime" / "linked_cache.json"
        original_resolve = Path.resolve
        def resolve_path(path: Path, *args: object, **kwargs: object) -> Path:
            if path == cache:
                return ROOT.parent / "private_file.json"
            return original_resolve(path, *args, **kwargs)
        with patch.object(Path, "resolve", resolve_path), patch("app.tools.web_search._fetch_snapshot") as fetch:
            with self.assertRaises(ToolFailure) as caught:
                search_remotive("AI Engineer", 3, cache_path=cache)
        self.assertEqual(caught.exception.code, "SEARCH_CACHE_BLOCKED")
        fetch.assert_not_called()

    def test_generic_query_does_not_call_source(self) -> None:
        with patch("app.tools.web_search._fetch_snapshot") as fetch:
            self.assertEqual(search_remotive("a jobs and roles", 3), [])
        fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
