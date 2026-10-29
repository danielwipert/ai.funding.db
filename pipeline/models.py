"""The one record that carries a Form D filing through every stage.

Each stage adds fields and never overwrites earlier ones. Fields for later
stages get added here as those stages are built; they default to None so
files written by earlier stages still load.
"""

from datetime import date, datetime

from pydantic import BaseModel


class Person(BaseModel):
    """A related person on the Form D: the outreach targets."""

    name: str
    relationships: list[str]  # Executive Officer, Director, Promoter
    clarification: str | None = None  # free text, often a title like "CEO"


class Filing(BaseModel):
    # Stage 1: Pull
    accession_no: str  # primary key: one Form D = one row
    cik: str
    company_name: str
    filing_date: date

    # Stage 2: Parse
    first_sale_date: date | None = None  # None when the first sale is "yet to occur"
    offering_total_usd: int | None = None  # None when "Indefinite"; can be a placeholder
    amount_sold_usd: int | None = None  # the real signal
    industry_group: str | None = None  # EDGAR's enum, verbatim
    state: str | None = None
    city: str | None = None
    related_persons: list[Person] | None = None
    is_amendment: bool | None = None
    previous_accession_no: str | None = None  # the filing a D/A amends
    parse_error: str | None = None  # set when the XML could not be fetched or read

    # Stage 3: Filter
    passed_structural: bool | None = None
    drop_reason: str | None = None  # set on every dropped row

    # Every stage
    run_id: str
    processed_at: datetime
