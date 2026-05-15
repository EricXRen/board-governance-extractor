"""Top-level board governance document model."""

from pydantic import BaseModel, ConfigDict, Field

from gov_extract.models.board_summary import BoardSummary
from gov_extract.models.director import Director
from gov_extract.models.director_election import DirectorElection
from gov_extract.models.metadata import CompanyMetadata


class BoardGovernanceDocument(BaseModel):
    """Complete extraction output: company metadata, all directors, board summary, and election."""

    model_config = ConfigDict(extra="forbid")

    company: CompanyMetadata
    directors: list[Director]
    board_summary: BoardSummary = Field(default_factory=BoardSummary)
    director_election: DirectorElection | None = None
