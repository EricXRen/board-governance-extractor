"""Models for the director election / proxy vote section of a filing."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from gov_extract.models.director import Director


class DirectorElectionSummary(BaseModel):
    """Aggregate summary of the director election proposed in the filing."""

    model_config = ConfigDict(extra="forbid")

    num_directors_to_elect: int | None = None
    incumbent_nominees: list[str] = []
    new_nominees: list[str] = []
    candidates_disclosed: bool | None = None


class DirectorElection(BaseModel):
    """Director election section: summary plus full candidate details."""

    model_config = ConfigDict(extra="forbid")

    summary: DirectorElectionSummary = Field(default_factory=DirectorElectionSummary)
    candidates: list[Director] = []
