"""A plan may select only known, read-only tools and validated arguments."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.tool import ReadProfileInput, SearchJobsInput


class StepBase(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    id: int = Field(ge=1, le=4)
    description: str = Field(min_length=1, max_length=300)
    status: Literal["pending", "running", "completed", "failed"] = "pending"


class ReadProfileStep(StepBase):
    tool: Literal["read_profile"]
    arguments: ReadProfileInput


class SearchJobsStep(StepBase):
    tool: Literal["search_jobs"]
    arguments: SearchJobsInput


# The tool name selects the corresponding argument schema, not arbitrary code.
TaskStep = Annotated[ReadProfileStep | SearchJobsStep, Field(discriminator="tool")]


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    steps: list[TaskStep] = Field(min_length=2, max_length=4)

    @model_validator(mode="after")
    def check_executable_order(self) -> "Plan":
        if [step.id for step in self.steps] != list(range(1, len(self.steps) + 1)):
            raise ValueError("Step IDs must start at 1 and be consecutive.")
        if self.steps[0].tool != "read_profile":
            raise ValueError("The first step must read the profile.")
        if any(step.tool != "search_jobs" for step in self.steps[1:]):
            raise ValueError("After the profile, use one to three job searches.")
        if any(step.status != "pending" for step in self.steps):
            raise ValueError("A new plan must contain only pending steps.")
        return self
