"""Board-level governance summary model."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class BoardSummary(BaseModel):
    """Aggregate governance statistics for the full board.

    Fields are populated from two sources (priority order):
    1. Explicitly stated values extracted from the filing text.
    2. Values computed from the extracted Director list (where derivable).

    Only ``voting_standard`` must come exclusively from the filing text;
    all other fields have a computation fallback.
    """

    model_config = ConfigDict(extra="forbid")

    # Governance structure
    ceo_chair_separated: bool | None = None
    voting_standard: Literal["Majority", "Plurality"] | None = None

    # Board composition
    board_size: int | None = None
    num_executive_directors: int | None = None
    num_non_executive_directors: int | None = None
    num_independent_directors: int | None = None

    # Diversity and demographics
    pct_women: float | None = None        # 0–100; computed from directors.biographical.gender
    pct_independent: float | None = None  # 0–100
    avg_director_age: float | None = None
    avg_tenure_years: float | None = None

    # Additional governance notes extracted from the filing
    notes: str | None = None
