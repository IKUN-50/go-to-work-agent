"""Provider-neutral contracts: tools know nothing about model vendors."""

from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ReadProfileInput(StrictModel):
    profile_name: Literal["profile.json"] = "profile.json"


class SearchJobsInput(StrictModel):
    query: str = Field(min_length=1, max_length=300)
    limit: int = Field(default=3, ge=1, le=5)

    @field_validator("query", mode="before")
    @classmethod
    def trim_query(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class ToolDefinition(StrictModel):
    name: str
    description: str
    input_schema: dict[str, Any]


class ToolError(StrictModel):
    code: str
    message: str
    retryable: bool = False


class ToolResult(StrictModel):
    tool: str
    success: bool
    data: dict[str, Any] | None = None
    error: ToolError | None = None

    @model_validator(mode="after")
    def consistent_result(self) -> "ToolResult":
        if self.success and (self.data is None or self.error is not None):
            raise ValueError("Successful tool results require data and no error.")
        if not self.success and (self.data is not None or self.error is None):
            raise ValueError("Failed tool results require an error and no data.")
        return self


class SearchItem(StrictModel):
    title: str = Field(min_length=1, max_length=300)
    url: str = Field(min_length=1, max_length=2000)
    snippet: str = Field(max_length=2000)
    source_kind: Literal["synthetic", "public_job_listing"]

    @field_validator("url")
    @classmethod
    def valid_http_url(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
            raise ValueError("Search results require an HTTP(S) URL without credentials.")
        # Accessing port also rejects malformed ports.
        _ = parts.port
        return value


class SearchJobsData(StrictModel):
    query: str = Field(min_length=1, max_length=300)
    items: list[SearchItem] = Field(max_length=5)
    source_mode: Literal["sample", "web"]
    warnings: list[str]

    @model_validator(mode="after")
    def matching_provenance(self) -> "SearchJobsData":
        expected = "synthetic" if self.source_mode == "sample" else "public_job_listing"
        if any(item.source_kind != expected for item in self.items):
            raise ValueError("Search provenance does not match the selected source.")
        return self


class JobSamples(StrictModel):
    sample: Literal[True]
    notice: str = Field(min_length=1, max_length=500)
    items: list[SearchItem] = Field(max_length=50)

    @model_validator(mode="after")
    def synthetic_only(self) -> "JobSamples":
        if any(item.source_kind != "synthetic" for item in self.items):
            raise ValueError("Sample fixtures must identify every item as synthetic.")
        return self
