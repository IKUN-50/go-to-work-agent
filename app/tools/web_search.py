"""Read a bounded Remotive public job snapshot and filter it locally.

Official API: https://github.com/remotive-com/remote-jobs-api
This is candidate discovery, not full job extraction or market analysis.
"""

import html
import ipaddress
import json
import re
import socket
import tempfile
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.schemas.tool import SearchItem
from app.tools.errors import ToolFailure

SEARCH_ENDPOINT = "https://remotive.com/api/remote-jobs"
SEARCH_TIMEOUT_SECONDS = 10
MAX_RESPONSE_BYTES = 1024 * 1024
CACHE_TTL_SECONDS = 6 * 60 * 60
CACHE_PATH = Path(__file__).resolve().parents[2] / "runtime" / "remotive_jobs_cache.json"

# Natural-language glue and job-search words cannot establish relevance alone.
GENERIC_TERMS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "i", "in",
    "is", "it", "my", "of", "on", "or", "the", "to", "with", "want", "would",
    "like", "find", "search", "looking", "look", "apply", "research", "current",
    "jobs", "job", "roles", "role", "positions", "position", "career", "work",
    "requirements", "required", "please", "help", "me", "some", "remote",
})
ALIASES = {
    "engineers": "engineer", "engineering": "engineer", "agents": "agent",
    "agentic": "agent", "developers": "developer", "applications": "application",
    "jr": "junior", "internship": "intern", "interns": "intern",
}
JUNIOR_MARKERS = frozenset({"junior", "intern", "graduate", "entry"})
ROLE_TERMS = frozenset({"engineer", "developer", "architect", "scientist", "designer", "manager", "analyst", "nurse", "chef"})
AI_DOMAINS = frozenset({"ai", "ml", "llm"})


class _RemotiveJob(BaseModel):
    """Only the source fields needed to establish a real job-listing record."""
    model_config = ConfigDict(extra="ignore", strict=True)

    id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=500)
    company_name: str = Field(min_length=1, max_length=300)
    url: str = Field(min_length=1, max_length=2000)
    description: str = Field(min_length=1, max_length=200000)
    publication_date: str = Field(min_length=1, max_length=80)
    candidate_required_location: str = Field(default="Unspecified", max_length=500)


class _RemotiveResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    jobs: list[_RemotiveJob] = Field(max_length=1000)


class _TextOnly(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _plain_text(value: str) -> str:
    parser = _TextOnly()
    parser.feed(value)
    return " ".join(html.unescape(" ".join(parser.parts)).split())


def _tokens(text: str) -> set[str]:
    normalized = text.casefold().replace("artificial intelligence", "ai").replace("人工智能", " ai ")
    normalized = normalized.replace("machine learning", "ml").replace("large language models", "llm").replace("large language model", "llm")
    words = re.findall(r"[a-z0-9+#]+|[\u4e00-\u9fff]+", normalized)
    return {ALIASES.get(word, word) for word in words}


def query_terms(query: str) -> set[str]:
    return _tokens(query) - GENERIC_TERMS


def matches_query(title: str, text: str, query: str) -> bool:
    """Conservative keyword match; generic words alone never qualify a result."""
    required = query_terms(query)
    if not required:
        return False
    title_words = _tokens(title)
    if not (required & ROLE_TERMS) <= title_words:
        return False
    if required & AI_DOMAINS and required & ROLE_TERMS and not title_words & AI_DOMAINS:
        return False
    if required & JUNIOR_MARKERS and not title_words & JUNIOR_MARKERS:
        return False
    if "junior" in required:
        required = required - {"junior"}
    if "senior" in required and "senior" not in title_words:
        return False
    # Every meaningful query token needs evidence, not just 'a' or 'jobs'.
    return required <= _tokens(title + " " + text)


def is_public_result_url(url: str) -> bool:
    """Reject obvious private/credential-bearing URLs. Result URLs are not fetched."""
    try:
        if any(ord(char) <= 32 for char in url):
            return False
        parts = urlsplit(url)
        host = (parts.hostname or "").lower().rstrip(".")
        if parts.scheme not in {"http", "https"} or parts.username or parts.password:
            return False
        if not host or parts.port not in {None, 80, 443}:
            return False
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".invalid", ".test")):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            suffix = host.rsplit(".", 1)[-1]
            return "." in host and (suffix.isalpha() or suffix.startswith("xn--")) and all(char.isalnum() or char in ".-" for char in host)
    except ValueError:
        return False


def is_remotive_listing_url(url: str) -> bool:
    if not is_public_result_url(url):
        return False
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.netloc == "remotive.com" and parts.path.startswith("/remote-jobs/")


class _SameEndpointRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Request | None:
        if newurl != SEARCH_ENDPOINT:
            raise ToolFailure("SEARCH_REDIRECT_BLOCKED", "The job service redirected outside the allowed endpoint.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _decode_snapshot(content: bytes) -> _RemotiveResponse:
    if len(content) > MAX_RESPONSE_BYTES:
        raise ToolFailure("SEARCH_TOO_LARGE", "The public job response exceeds the size limit.")
    try:
        return _RemotiveResponse.model_validate(json.loads(content.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError):
        raise ToolFailure("SEARCH_FORMAT_INVALID", "The job service did not return the expected job-listing schema.") from None


def _excerpt(title: str, description: str, query: str) -> str:
    """Keep short source excerpts around matches, without creating inferred claims."""
    parts = [description[:350]]
    # Include later matching evidence so the registry can recheck visible output.
    for word in sorted(query_terms(query) - _tokens(title)):
        match = re.search(r"\b" + re.escape(word) + r"\w*\b", description, re.IGNORECASE)
        if match:
            parts.append(description[max(0, match.start() - 60):match.end() + 120])
    return " ... ".join(dict.fromkeys(parts))[:1400]


def parse_remotive_snapshot(content: bytes, query: str, limit: int) -> list[SearchItem]:
    snapshot = _decode_snapshot(content)
    results: list[SearchItem] = []
    seen: set[str] = set()
    for job in snapshot.jobs:
        if job.url in seen or not is_remotive_listing_url(job.url):
            continue
        title = _plain_text(job.title)[:300]
        description = _plain_text(job.description)
        if not matches_query(title, description, query):
            continue
        context = f"Source: Remotive | Company: {job.company_name} | Published: {job.publication_date} | Location: {job.candidate_required_location}. "
        snippet = (context[:500] + _excerpt(title, description, query))[:2000]
        if not matches_query(title, snippet, query):
            continue
        results.append(SearchItem(title=title, url=job.url, snippet=snippet, source_kind="public_job_listing"))
        seen.add(job.url)
        if len(results) >= limit:
            break
    return results


def _fetch_snapshot() -> bytes:
    request = Request(SEARCH_ENDPOINT, headers={"User-Agent": "CareerIntelligenceAgent/0.1", "Accept": "application/json"})
    try:
        with build_opener(_SameEndpointRedirect()).open(request, timeout=SEARCH_TIMEOUT_SECONDS) as response:
            content = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as error:
        if error.code == 429:
            raise ToolFailure("SEARCH_RATE_LIMITED", "Remotive rate-limited this request. Try later; automatic retry is disabled.") from None
        raise ToolFailure("SEARCH_HTTP_ERROR", "The public job service returned an HTTP error.", error.code == 408 or error.code >= 500) from None
    except (TimeoutError, socket.timeout):
        raise ToolFailure("SEARCH_TIMEOUT", "The public job request timed out.", True) from None
    except (URLError, OSError):
        raise ToolFailure("SEARCH_UNAVAILABLE", "The public job service could not be reached.", True) from None
    _decode_snapshot(content)
    return content


def _validate_cache_path(path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    if root not in path.resolve().parents or path.resolve() != path.absolute():
        raise ToolFailure("SEARCH_CACHE_BLOCKED", "The public-job cache must stay inside this repository without linked paths.")


def _atomic_write(path: Path, content: bytes) -> None:
    _validate_cache_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix="remotive-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _load_snapshot(cache_path: Path) -> tuple[bytes, str]:
    """Six-hour public-data cache avoids repeatedly polling Remotive from the CLI."""
    try:
        _validate_cache_path(cache_path)
        if cache_path.exists() and 0 <= time.time() - cache_path.stat().st_mtime < CACHE_TTL_SECONDS:
            with cache_path.open("rb") as stream:
                content = stream.read(MAX_RESPONSE_BYTES + 1)
            _decode_snapshot(content)
            return content, "hit"
        marker = cache_path.parent / "remotive_last_request.txt"
        _validate_cache_path(marker)
        if marker.exists() and 0 <= time.time() - marker.stat().st_mtime < 60:
            raise ToolFailure("SEARCH_COOLDOWN", "The job source was requested recently. Wait at least one minute before trying again.")
        # No query, profile, response body or exception is written to this marker.
        _atomic_write(marker, b"public-job-request\n")
        content = _fetch_snapshot()
        _atomic_write(cache_path, content)
        return content, "refreshed"
    except OSError:
        raise ToolFailure("SEARCH_CACHE_UNAVAILABLE", "The local public-job cache could not be read or saved.") from None


class RemotiveSearch:
    """A callable source retaining only public snapshot metadata for attribution."""
    def __init__(self, cache_path: Path | None = None) -> None:
        self.cache_path = cache_path if cache_path is not None else CACHE_PATH
        self.status_note = "No public-source request has been made."

    def __call__(self, query: str, limit: int) -> list[SearchItem]:
        if not query_terms(query):
            self.status_note = "No distinctive search terms were supplied; no public-source request was made."
            return []
        content, status = _load_snapshot(self.cache_path)
        fetched_at = datetime.fromtimestamp(self.cache_path.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds")
        self.status_note = f"Remotive public snapshot fetched at {fetched_at}; cache status: {status}. Publication dates are shown per item."
        return parse_remotive_snapshot(content, query, limit)


def search_remotive(query: str, limit: int, *, cache_path: Path | None = None) -> list[SearchItem]:
    return RemotiveSearch(cache_path)(query, limit)
