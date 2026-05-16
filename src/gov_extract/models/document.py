"""Top-level board governance document model."""

from pydantic import BaseModel, ConfigDict, Field

from gov_extract.models.board_summary import BoardSummary
from gov_extract.models.director import Director
from gov_extract.models.director_election import DirectorElection
from gov_extract.models.metadata import CompanyMetadata


class Board(BaseModel):
    """Current board composition: aggregate summary plus individual director details."""

    model_config = ConfigDict(extra="forbid")

    summary: BoardSummary = Field(default_factory=BoardSummary)
    directors: list[Director] = []


class BoardGovernanceDocument(BaseModel):
    """Complete extraction output: company metadata, current board, and director election."""

    model_config = ConfigDict(extra="forbid")

    company: CompanyMetadata
    current_board: Board = Field(default_factory=Board)
    director_election: DirectorElection | None = None
    post_election_board: Board | None = None
