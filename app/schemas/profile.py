"""Small profile contract; the bundled demo is explicitly fictional."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProfileData(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    sample: bool
    display_name: str = Field(min_length=1, max_length=100)
    goal: str = Field(min_length=1, max_length=500)
    skills: dict[str, Literal["beginner", "learning", "not_started", "intermediate", "advanced"]] = Field(max_length=50)
    notice: str = Field(min_length=1, max_length=500)
