"""
fetch_tona.py
=============
Scraper for TONA (Tokyo Overnight Average rate) from Bank of Japan.

Source:   Bank of Japan — Time-Series Data Search REST API v1
Endpoint: https://www.stat-search.boj.or.jp/api/v1/getDataCode
Updated:  Daily (verified empirically 2026-05-31, LAST_UPDATE: 20260529)

History of this scraper:
    The previous version of this scraper used two legacy endpoints:
        - Primary:  /stat/data/STRDCLUCON.json
        - Fallback: /ssi/cgi-bin/famecgi2 (CGI legacy)
    Both endpoints returned HTML error pages ("Page cannot be displayed")
    after the BoJ migrated to a new REST API. The new API uses a different
    URL structure and JSON schema.

API parameters:
    db          = "FM01"           ← Financial Markets 01 database
    code        = "STRDCLUCON"     ← Call Rate, Uncollateralized Overnight, Average Daily
    format      = "json"
    lang        = "en"
    startDate   = "YYYYMM"          (monthly range, not daily)
    endDate     = "YYYYMM"

Full series code in BoJ portal: FM01'STRDCLUCON
    - "FM01" is the database (passed as `db=` parameter)
    - "STRDCLUCON" is the series code (passed as `code=` parameter)
    - The apostrophe + db prefix in the portal display is NOT used in the API

Response schema (verified empirically with real JSON):
    {
      "STATUS": 200,                       # int, not string
      "RESULTSET": [
        {
          "SERIES_CODE": "STRDCLUCON",
          "VALUES": {
            "SURVEY_DATES": [20260401, ...],   # int YYYYMMDD
            "VALUES": [0.728, null, 0.727, ...] # float or null
          }
        }
      ]
    }

    - Dates come as integers in YYYYMMDD format (not strings)
    - Values come as floats in percent (e.g. 0.728 = 0.728%)
    - null indicates no trading day (weekend, holiday)
    - Both arrays have same length and index correspondence

Output:
    data/TONA.csv  — daily TONA in OHLCV format

License: Bank of Japan public statistics. The BoJ Time-Series Data Search
         is publicly accessible and supports programmatic access via this
         documented REST API.
"""

import csv
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests


# Constants
BOJ_URL = "https://www.stat-search.boj.or.jp/api/v1/getDataCode"
DB_CODE = "FM01"
SERIES_CODE = "STRDCLUCON"
HISTORY_YEARS = 5
TIMEOUT_SECONDS = 45
USER_AGENT = "xccy-g8/1.0 (https://github.com/sanderdayan1982/xccy-g8)"

OUTPUT_FILENAME = "TONA.csv"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data"


def _fetch_month_range(
    start_yyyymm: str,
    end_yyyymm: str,
) -> list[tuple[str, float]]:
    """
    Fetch TONA data for the given monthly range.

    Returns list of (YYYYMMDD_str, value_percent) tuples, only for days that
    have non-null values. Sorted ascending by date.
    """
    params = {
        "format": "json",
        "lang": "en",
        "db": DB_CODE,
        "code": SERIES_CODE,
        "startDate": start_yyyymm,
        "endDate": end_yyyymm,
    }
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}

    response = requests.get(BOJ_URL, params=params, headers=headers, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()

    try:
        data = response.json()
    except json.JSONDecodeError as exc:
        raise ValueError(f"BoJ API returned non-JSON response: {exc}")

    # API status check (note: STATUS is an integer, not a string)
    status = data.get("STATUS")
    if status != 200:
        message = data.get("MESSAGE", "(no message)")
        msgid = data.get("MESSAGEID", "(no id)")
        raise ValueError(f"BoJ API error: STATUS={status}, MESSAGE={message}, ID={msgid}")

    # Extract the series from RESULTSET (not DATA_INF.SERIES as some docs suggest)
    resultset = data.get("RESULTSET")
    if not resultset or not isinstance(resultset, list):
        raise ValueError(f"BoJ API: missing or empty RESULTSET (got {type(resultset).__name__})")

    # Find the matching series (defensive: always look up by SERIES_CODE)
    series = None
    for s in resultset:
        if s.get("SERIES_CODE") == SERIES_CODE:
            series = s
            break

    if series is None:
        codes_found = [s.get("SERIES_CODE") for s in resultset]
        raise ValueError(
            f"BoJ API: expected SERIES_CODE={SERIES_CODE!r}, got {codes_found}"
        )

    # Values are nested: RESULTSET[i].VALUES.SURVEY_DATES and .VALUES
    values_obj = series.get("VALUES")
    if not isinstance(values_obj, dict):
        raise ValueError(
            f"BoJ API: expected SERIES.VALUES to be dict, got {type(values_obj).__name__}"
        )

    survey_dates = values_obj.get("SURVEY_DATES", [])
    values_arr = values_obj.get("VALUES", [])

    if not survey_dates or not values_arr:
        raise ValueError(
            f"BoJ API: empty SURVEY_DATES ({len(survey_dates)}) or "
            f"VALUES ({len(values_arr)}) arrays"
        )

    if len(survey_dates) != len(values_arr):
        raise ValueError(
            f"BoJ API: array length mismatch: "
            f"SURVEY_DATES={len(survey_dates)} vs VALUES={len(values_arr)}"
        )

    rows: list[tuple[str, float]] = []
    for raw_date, raw_value in zip(survey_dates, values_arr):
        # Skip null values (weekends, holidays)
        if raw_value is None:
            continue

        # Date comes as integer YYYYMMDD (e.g. 20260401)
        date_str = str(raw_date)
        if len(date_str) != 8:
            continue

        # Validate it's a real date (defensive)
        try:
            datetime.strptime(date_str, "%Y%m%d")
        except ValueError:
            continue

        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            continue

        rows.append((date_str, value))

    rows.sort(key=lambda r: r[0])
    return rows


def fetch_tona(
    date_from: datetime,
    date_to: datetime,
) -> list[tuple[str, float]]:
    """
    Fetch TONA data spanning [date_from, date_to].

    BoJ API takes monthly range (YYYYMM), so we request the entire range
    in a single call. The API handles spans of up to ~6 years cleanly.
    """
    start_yyyymm = date_from.strftime("%Y%m")
    end_yyyymm = date_to.strftime("%Y%m")

    return _fetch_month_range(start_yyyymm, end_yyyymm)


def write_csv(rows: list[tuple[str, float]], output_path: Path) -> None:
    """Write rows to OHLCV format CSV (O=H=L=C for daily rates, V=0)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["DATE", "OPEN", "HIGH", "LOW", "CLOSE", "VOLUME"])
        for date_str, value in rows:
            v = f"{value:.4f}"
            writer.writerow([date_str, v, v, v, v, "0"])


def main() -> int:
    today = datetime.utcnow()
    date_from = today - timedelta(days=365 * HISTORY_YEARS)

    print(f"Fetching TONA from {date_from.date()} to {today.date()}")
    print(f"Source: BoJ Time-Series Data Search REST API v1")
    print(f"Database: {DB_CODE}, Series: {SERIES_CODE}")
    print(
        f"Monthly range: {date_from.strftime('%Y%m')} to {today.strftime('%Y%m')}"
    )
    print()

    try:
        rows = fetch_tona(date_from, today)
    except requests.HTTPError as exc:
        print(f"ERROR: BoJ HTTP error: {exc}", file=sys.stderr)
        return 1
    except requests.RequestException as exc:
        print(f"ERROR: BoJ network error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR: TONA fetch failed: {exc}", file=sys.stderr)
        return 1

    if not rows:
        print("ERROR: No rows returned", file=sys.stderr)
        return 1

    output_path = OUTPUT_DIR / OUTPUT_FILENAME
    write_csv(rows, output_path)
    print(f"OK: Wrote {len(rows)} rows to {OUTPUT_FILENAME}")
    print(f"    Latest:   {rows[-1][0]} = {rows[-1][1]:.4f}%")
    print(f"    Earliest: {rows[0][0]} = {rows[0][1]:.4f}%")

    return 0


if __name__ == "__main__":
    sys.exit(main())
