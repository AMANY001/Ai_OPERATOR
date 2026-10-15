"""Validated data contracts shared by the planner and tool layer."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field, HttpUrl, ConfigDict


class PlanDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workflow: Literal["opportunity_search", "web_research", "unsupported"]
    category: Literal["internship", "job", "general"]
    query: str = Field(min_length=3, max_length=500)
    limit: int = Field(default=10, ge=1, le=30)
    reason: str = Field(default="", max_length=500)
    unsupported_reason: str = Field(default="", max_length=500)


class Opportunity(BaseModel):
    model_config = ConfigDict(extra="allow")
    title: str = Field(min_length=1, max_length=300)
    company: str = Field(default="Unknown", max_length=200)
    location: str = Field(default="Not stated", max_length=200)
    eligibility: str = Field(default="Not stated in source", max_length=1000)
    deadline: str = Field(default="Not stated", max_length=100)
    link: str = Field(min_length=1, max_length=2000)
    description: str = Field(default="", max_length=5000)
    source_mode: str = Field(default="live_search", max_length=40)
    verification_status: str = Field(default="unverified", max_length=40)
    is_sample: bool = False
    fit_score: int = Field(default=0, ge=0, le=100)
    ranking_reasons: list[str] = Field(default_factory=list)
