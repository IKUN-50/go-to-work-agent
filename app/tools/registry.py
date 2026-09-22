"""Validate, dispatch and contain failures; the Executor owns retries."""

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from app.schemas.tool import JobSamples, ReadProfileInput, SearchItem, SearchJobsData, SearchJobsInput, ToolDefinition, ToolError, ToolResult
from app.tools.errors import ToolFailure
from app.tools.profile_reader import read_allowed_json, read_profile
from app.tools.web_search import RemotiveSearch, is_remotive_listing_url, matches_query

INPUT_MODELS = {"read_profile": ReadProfileInput, "search_jobs": SearchJobsInput}
SearchBackend = Callable[[str, int], list[SearchItem]]
SEARCH_STOP_WORDS = frozenset({"a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "i", "in", "is", "it", "my", "of", "on", "or", "the", "to", "with"})


def _search_tokens(text: str) -> set[str]:
    tokens = set(re.findall(r"[a-z0-9+#]+|[\u4e00-\u9fff]+", text.casefold()))
    return tokens - SEARCH_STOP_WORDS


class ToolRegistry:
    def __init__(self, data_dir: Path | None = None, search_mode: Literal["sample", "web"] = "sample", search_backend: SearchBackend | None = None) -> None:
        if search_mode not in {"sample", "web"}:
            raise ValueError("Search mode must be sample or web.")
        self.data_dir = data_dir if data_dir is not None else Path(__file__).resolve().parents[2] / "data"
        self.search_mode = search_mode
        self.search_backend = search_backend or RemotiveSearch()

    def definitions(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(name="read_profile", description="Read the configured local learning profile; only profile.json is allowed. The bundled profile is explicitly fictional.", input_schema=ReadProfileInput.model_json_schema()),
            ToolDefinition(name="search_jobs", description="Find candidate job sources. Sample mode uses synthetic examples. Web mode filters a limited Remotive remote-job snapshot by meaningful query terms; junior queries require junior evidence in the title. It does not verify whether jobs are still open.", input_schema=SearchJobsInput.model_json_schema()),
        ]

    def validate_arguments(self, name: str, arguments: dict[str, Any]) -> None:
        model = INPUT_MODELS.get(name)
        if model is None:
            raise ValueError("Unknown tool.")
        try:
            model.model_validate(arguments)
        except ValidationError:
            raise ValueError("Tool input failed schema validation.") from None

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        if name not in INPUT_MODELS:
            # Do not echo arbitrary model output as the tool name.
            return self._failure("unknown", "UNKNOWN_TOOL", "The requested tool is not available.")
        try:
            self.validate_arguments(name, arguments)
        except ValueError:
            return self._failure(name, "INVALID_TOOL_INPUT", "Tool input failed schema validation.")
        try:
            if name == "read_profile":
                data = read_profile(self.data_dir)
            else:
                data = self._search(SearchJobsInput.model_validate(arguments))
            return ToolResult(tool=name, success=True, data=data.model_dump(mode="json"))
        except ToolFailure as error:
            return self._failure(name, error.code, error.message, error.retryable)
        except ValidationError:
            return self._failure(name, "INVALID_TOOL_OUTPUT", "Tool output failed schema validation.")
        except (TimeoutError, ConnectionError):
            return self._failure(name, "TOOL_UNAVAILABLE", "The tool is temporarily unavailable.", True)
        except Exception:
            # Unknown adapter/backend failures still stay inside the tool boundary.
            return self._failure(name, "TOOL_ERROR", "The tool could not complete the request.")

    @staticmethod
    def _failure(name: str, code: str, message: str, retryable: bool = False) -> ToolResult:
        return ToolResult(tool=name, success=False, error=ToolError(code=code, message=message, retryable=retryable))

    def _search(self, args: SearchJobsInput) -> SearchJobsData:
        if self.search_mode == "sample":
            samples = JobSamples.model_validate(read_allowed_json(self.data_dir, "job_samples.json"))
            tokens = _search_tokens(args.query)
            scores = [
                (len(tokens & _search_tokens(item.title + " " + item.snippet)), index, item)
                for index, item in enumerate(samples.items)
            ]
            ranked = sorted(scores, key=lambda entry: (-entry[0], entry[1]))
            items = [item for score, _, item in ranked if score > 0][:args.limit]
            warnings = ["Synthetic learning examples only; these are not live vacancies or evidence of current market requirements."]
        else:
            # Validate injected backends as strictly as the real network backend.
            items = self.search_backend(args.query, args.limit)
            warnings = [
                "Source: Remotive public API (https://remotive.com). Limited remote-job coverage, not a search of the whole market. Keep the original Remotive listing links and attribution.",
                "Remotive public listings are delayed by 24 hours; this app caches the public snapshot for up to six more hours to avoid frequent requests.",
                "Conservative local keyword matching can miss relevant jobs. Returned excerpts are not full job pages; current vacancy status, eligibility and application availability have not been verified.",
            ]
            if isinstance(self.search_backend, RemotiveSearch):
                warnings.append(self.search_backend.status_note)
        result = SearchJobsData(query=args.query, items=items, source_mode=self.search_mode, warnings=warnings)
        if len(result.items) > args.limit:
            raise ToolFailure("INVALID_TOOL_OUTPUT", "Search output exceeded the requested result limit.")
        if self.search_mode == "web" and any(not is_remotive_listing_url(item.url) for item in result.items):
            raise ToolFailure("INVALID_TOOL_OUTPUT", "The search output contained a disallowed result URL.")
        if self.search_mode == "web":
            result.items = [item for item in result.items if matches_query(item.title, item.snippet, args.query)]
        if not result.items:
            result.warnings.append("No matching results were returned; no alternative source was selected automatically.")
        return result
