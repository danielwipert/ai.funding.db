"""The one record that carries a Form D filing through every stage.

Each stage adds fields and never overwrites earlier ones. Fields for later
stages get added here as those stages are built.
"""

from datetime import date, datetime

from pydantic import BaseModel


class Filing(BaseModel):
    # Stage 1: Pull
    accession_no: str  # primary key: one Form D = one row
    cik: str
    company_name: str
    filing_date: date

    # Every stage
    run_id: str
    processed_at: datetime
