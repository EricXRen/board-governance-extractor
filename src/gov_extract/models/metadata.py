"""Company-level metadata model."""

from pydantic import BaseModel, ConfigDict


class CompanyMetadata(BaseModel):
    """Metadata about the filing and extraction run."""

    model_config = ConfigDict(extra="forbid")

    company_name: str
    company_ticker: str | None = None
    filing_type: str
    fiscal_year_end: str
    report_date: str | None = None
    source_pdf_path: str
    extraction_timestamp: str
    llm_provider: str
    llm_model: str
