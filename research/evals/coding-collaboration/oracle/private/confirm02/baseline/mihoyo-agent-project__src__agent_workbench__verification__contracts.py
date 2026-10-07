"""Frozen business input, independent of graph state and game implementation."""
import hashlib
import json
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, model_validator


def canonical(value) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def fingerprint(value) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Bound(ClosedModel):
    minimum: float
    maximum: float


class Change(ClosedModel):
    path: str = Field(min_length=1, max_length=160)
    value: StrictInt | StrictFloat


class ExperimentPlan(ClosedModel):
    schema_version: Literal["experiment-v1"] = "experiment-v1"
    request_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    request: str = Field(min_length=1, max_length=4000)
    game_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    changes: list[Change] = Field(min_length=1, max_length=10)
    bounds: dict[str, Bound]
    seeds: list[StrictInt] = Field(min_length=1, max_length=20)
    policies: list[Literal["balanced", "survival", "basic_only"]] = Field(min_length=1, max_length=3)
    max_battles: int = Field(ge=1, le=120, strict=True)
    profile: Literal["descriptive-v1"] = "descriptive-v1"

    @model_validator(mode="after")
    def bounded_manifest(self):
        if len(set(self.seeds)) != len(self.seeds) or any(type(s) is not int or not 0 <= s < 2**63 for s in self.seeds):
            raise ValueError("seeds must be unique nonnegative integers")
        if len(set(self.policies)) != len(self.policies):
            raise ValueError("policies must be unique")
        if self.battles > self.max_battles:
            raise ValueError("battle budget is smaller than the frozen paired manifest")
        if not 1 <= len(self.bounds) <= 10 or any(b.minimum > b.maximum for b in self.bounds.values()):
            raise ValueError("invalid authorized bounds")
        return self

    @property
    def battles(self) -> int:
        return 2 * len(self.seeds) * len(self.policies)


class GamePort(Protocol):
    """One concrete game adapter today, not a claim of arbitrary-game support."""
    def validate(self, plan: ExperimentPlan) -> dict: ...
    def execute(self, plan: ExperimentPlan) -> dict: ...
