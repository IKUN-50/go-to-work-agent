"""State describes what actually happened, separately from the proposed plan."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.plan import TaskStep
from app.schemas.report import Phase1Report
from app.schemas.tool import ToolError


class Observation(BaseModel):
    step_id: int
    tool: str
    success: bool
    data: dict[str, Any] | None = None
    error: ToolError | None = None
    attempts: int = Field(ge=1)


class TraceEvent(BaseModel):
    node: str
    step_id: int | None = None
    tool: str | None = None
    input_summary: str = ""
    result_summary: str = ""
    duration_ms: float = Field(ge=0)
    success: bool
    retry_count: int = Field(default=0, ge=0)
    error_code: str | None = None


class AgentState(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    goal: str = Field(min_length=1, max_length=2000)
    status: Literal["planning", "executing", "completed", "failed"] = "planning"
    plan: list[TaskStep] = Field(default_factory=list)
    # Zero-based position; len(plan) means every step has finished.
    current_step: int = 0
    observations: list[Observation] = Field(default_factory=list)
    errors: list[ToolError] = Field(default_factory=list)
    trace: list[TraceEvent] = Field(default_factory=list)
    final_report: Phase1Report | None = None
