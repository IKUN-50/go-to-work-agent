"""Phase 1 collects evidence; it does not claim to analyze the job market."""

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.profile import ProfileData
from app.schemas.tool import SearchJobsData


class Phase1Report(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: str
    summary: str
    profile: ProfileData
    searches: list[SearchJobsData] = Field(min_length=1)
    limitations: list[str]
    next_steps: list[str] = Field(default_factory=lambda: [
        "Phase 2: read job pages, extract structured postings and count skills.",
        "Phase 2: compare skill gaps and create the seven-day learning plan.",
        "Phase 3: add independent verification and richer recovery/approval.",
    ])

    @property
    def source_count(self) -> int:
        return len({item.url for search in self.searches for item in search.items})
