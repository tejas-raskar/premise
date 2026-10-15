from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

Text = Annotated[str, Field(min_length=1, max_length=10000)]
Identifier = Annotated[str, Field(min_length=1, max_length=200)]
Outcome = Literal["true", "false", "unknown"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Source(Input):
    uri: Text
    note: str = Field(max_length=10000)


class Requirement(Input):
    contract: Identifier
    expected: StrictBool


class Recall(Input):
    project: Identifier
    revision: Identifier
    decision_id: Identifier | None = None


class Mutation(Input):
    project: Identifier
    request_id: Identifier


class RecordDecision(Mutation):
    revision: Identifier
    statement: Text
    scope: Identifier
    sources: list[Source] = Field(max_length=50)
    supports: list[Annotated[list[Requirement], Field(min_length=1, max_length=50)]] = Field(
        min_length=1, max_length=20
    )

    @model_validator(mode="after")
    def distinct_requirements(self):
        for group in self.supports:
            if len({item.contract for item in group}) != len(group):
                raise ValueError("Each support must contain distinct contracts")
        return self


class AssessChanges(Mutation):
    base: Identifier
    target: Identifier


class RunCheck(Mutation):
    revision: Identifier
    contract: Identifier


class ProposeReplacement(RecordDecision):
    replaces: Identifier
    reason: Text


class AcceptProposal(Mutation):
    proposal_id: Identifier


class MemoryError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def evaluate_supports(supports: list[list[dict]], values: dict[str, tuple[str, str]]) -> str:
    groups = []
    for group in supports:
        resolved = [(values[item["contract"]], item["expected"]) for item in group]
        if any(
            value in ("true", "false") and (value == "true") != expected
            for (value, _), expected in resolved
        ):
            groups.append("contradicted")
        elif all(value in ("true", "false") for (value, _), _ in resolved):
            groups.append("supported")
        elif any(freshness != "stale" for (value, freshness), _ in resolved if value == "unknown"):
            groups.append("unknown")
        else:
            groups.append("needs_revalidation")
    if "supported" in groups:
        return "supported"
    if all(group == "contradicted" for group in groups):
        return "contradicted"
    return "unknown" if "unknown" in groups else "needs_revalidation"
