"""Shared HTTP access to SEC EDGAR.

The SEC requires a User-Agent with contact details and allows about
10 requests per second. Every EDGAR call goes through get_json() so both
rules are applied in one place.
"""

import os
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

MIN_SECONDS_BETWEEN_REQUESTS = 0.15  # stays under the SEC's ~10 req/s

_session = None
_last_request_at = 0.0


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        email = os.environ.get("EDGAR_CONTACT_EMAIL")
        if not email:
            raise SystemExit(
                "Set EDGAR_CONTACT_EMAIL first; the SEC requires contact details "
                "in every request. Example:\n  export EDGAR_CONTACT_EMAIL=you@example.com"
            )
        _session = requests.Session()
        _session.headers["User-Agent"] = f"AI Funding Scanner {email}"
        retry = Retry(total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
        _session.mount("https://", HTTPAdapter(max_retries=retry))
    return _session


def get_json(url: str, params: dict | None = None) -> dict:
    """GET a URL from EDGAR and return the parsed JSON, respecting the rate limit."""
    global _last_request_at
    wait = MIN_SECONDS_BETWEEN_REQUESTS - (time.monotonic() - _last_request_at)
    if wait > 0:
        time.sleep(wait)
    _last_request_at = time.monotonic()

    response = _get_session().get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json()
