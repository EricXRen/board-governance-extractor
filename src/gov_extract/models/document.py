"""Top-level board governance document model."""

from pydantic import BaseModel, ConfigDict

from gov_extract.models.director import Director
from gov_extract.models.metadata import CompanyMetadata


class BoardGovernanceDocument(BaseModel):
    """Complete extraction output: company metadata + all directors."""

    model_config = ConfigDict(extra="forbid")

    company: CompanyMetadata
    directors: list[Director]
