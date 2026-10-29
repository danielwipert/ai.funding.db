"""Stage 2: Parse each filing's Form D XML into the data model.

Reads runs/<run_id>/01_filings.jsonl and writes runs/<run_id>/02_parsed.jsonl.
Every XML is cached in cache/edgar/, so a second run downloads nothing.

Usage:
    python -m pipeline.parse                    # today's run folder
    python -m pipeline.parse --run-id 2026-10-28
"""

import argparse
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from pathlib import Path

import requests

from pipeline.edgar import get_bytes
from pipeline.models import Filing, Person

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "runs"
CACHE_DIR = ROOT / "cache" / "edgar"


def xml_url(cik: str, accession_no: str) -> str:
    return (
        f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
        f"{accession_no.replace('-', '')}/primary_doc.xml"
    )


def fetch_xml(cik: str, accession_no: str) -> tuple[bytes, bool]:
    """Return a filing's XML and whether it had to be downloaded."""
    cache_path = CACHE_DIR / f"{accession_no}.xml"
    if cache_path.exists():
        return cache_path.read_bytes(), False
    data = get_bytes(xml_url(cik, accession_no))
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(data)
    return data, True


def text(element: ET.Element, path: str) -> str | None:
    """Text at a path, or None when the tag is missing or empty."""
    found = element.find(path)
    if found is None or found.text is None or not found.text.strip():
        return None
    return found.text.strip()


def to_int(value: str | None) -> int | None:
    """Dollar amounts are digits, but can also be words like "Indefinite"."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def parse_person(info: ET.Element) -> Person:
    # firstName is sometimes a placeholder "." when the person is a company
    parts = [text(info, f"relatedPersonName/{tag}") for tag in ("firstName", "middleName", "lastName")]
    name = " ".join(p for p in parts if p and p != ".")
    return Person(
        name=name,
        relationships=[r.text.strip() for r in info.iterfind("relatedPersonRelationshipList/relationship") if r.text],
        clarification=text(info, "relationshipClarification"),
    )


def parse_xml(data: bytes) -> dict:
    """Map the Form D XML onto the stage 2 fields of the data model."""
    root = ET.fromstring(data)
    first_sale = text(root, "offeringData/typeOfFiling/dateOfFirstSale/value")
    return {
        "first_sale_date": date.fromisoformat(first_sale) if first_sale else None,
        "offering_total_usd": to_int(text(root, "offeringData/offeringSalesAmounts/totalOfferingAmount")),
        "amount_sold_usd": to_int(text(root, "offeringData/offeringSalesAmounts/totalAmountSold")),
        "industry_group": text(root, "offeringData/industryGroup/industryGroupType"),
        "state": text(root, "primaryIssuer/issuerAddress/stateOrCountry"),
        "city": text(root, "primaryIssuer/issuerAddress/city"),
        "related_persons": [parse_person(p) for p in root.iterfind("relatedPersonsList/relatedPersonInfo")],
        "is_amendment": text(root, "offeringData/typeOfFiling/newOrAmendment/isAmendment") == "true",
        "previous_accession_no": text(root, "offeringData/typeOfFiling/newOrAmendment/previousAccessionNumber"),
    }


def parse(run_id: str) -> Path:
    in_path = RUNS_DIR / run_id / "01_filings.jsonl"
    out_path = RUNS_DIR / run_id / "02_parsed.jsonl"
    filings = [Filing.model_validate_json(line) for line in in_path.read_text().splitlines()]
    processed_at = datetime.now(timezone.utc)

    downloaded = errors = 0
    with out_path.open("w") as out:
        for i, filing in enumerate(filings, start=1):
            try:
                data, was_downloaded = fetch_xml(filing.cik, filing.accession_no)
                downloaded += was_downloaded
                fields = parse_xml(data)
            except (requests.RequestException, ET.ParseError, ValueError) as e:
                fields = {"parse_error": f"{type(e).__name__}: {e}"}
                errors += 1
            parsed = filing.model_copy(update={**fields, "processed_at": processed_at})
            out.write(parsed.model_dump_json() + "\n")
            if i % 100 == 0:
                print(f"  {i}/{len(filings)} parsed")

    print(f"Wrote {len(filings)} rows to {out_path} ({downloaded} downloaded, {errors} errors)")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-id", default=date.today().isoformat(), help="run folder name (default: today)")
    args = parser.parse_args()
    parse(args.run_id)


if __name__ == "__main__":
    main()
