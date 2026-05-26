"""
fetch_tona.py
=============
Scraper for Tokyo Overnight Average Rate (TONA) from Bank of Japan.

Source:   BoJ Time-Series Data Search (English interface)
Endpoint: https://www.stat-search.boj.or.jp/ssi/cgi-bin/famecgi2
Series:   IR01'MUTCALAL (Mutan call rate, average, overnight)
Format:   CSV (with BoJ-specific quirks: BOM, latin-1/shift-jis mixed encoding,
          metadata in first ~5 rows)

Output:
    data/TONA.csv  — TONA historical series in OHLCV format

License: Data sourced from Bank of Japan public statistics.
         BoJ retains all rights to source data.

Notes:
    BoJ CSV format has historically been the most volatile of the G7 RFR
    sources. This scraper uses defensive parsing: it looks for a date
    column in the first N columns and accepts multiple date formats.
    If BoJ changes endpoint structure, the failure mode is explicit
    (clear error message) rather than silent wrong data.
"""

import csv
import sys
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path

import requests


# Constants
BOJ_URL = "https://www.stat-search.boj.or.jp/ssi/cgi-bin/famecgi2"
SERIES_CODE = "IR01'MUTCALAL"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "TONA.csv"
HISTORY_YEARS = 5
TIMEOUT_SECONDS = 30
USER_AGENT = "xccy-g8/1.0 (https://github.com/sanderdayan1982/xccy-g8)"


def build_request_params(date_from: datetime, date_to: datetime) -> dict:
    """Build BoJ form-based query parameters for TONA series."""
    return {
        "cgi": "$nme_a000_en",
        "rep_date": "1",
        "hdnSeriesCodeList": SERIES_CODE,
        "hdnRSMode": "EXP",
        "hdnYyyyFrom": str(date_from.year),
        "hdnMmFrom": f"{date_from.month:02d}",
        "hdnDdFrom": f"{date_from.day:02d}",
        "hdnYyyyTo": str(date_to.year),
        "hdnMmTo": f"{date_to.month:02d}",
        "hdnDdTo": f"{date_to.day:02d}",
        "hdnCsvDownload": "1",
        "hdnExpType": "csv",
    }


def _try_parse_boj_date(s: str) -> datetime | None:
    """
    BoJ uses multiple date formats depending on download path:
        YYYY/MM/DD
        YYYY-MM-DD
        YYYYMMDD
    Returns None if not parseable.
    """
    s = s.strip().strip('"')
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _try_parse_value(s: str) -> float | None:
    """BoJ uses commas as thousand separators in some exports; clean defensively."""
    s = s.strip().strip('"').replace(",", "")
    if not s or s in ("-", "N/A", "NA", "..."):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def find_date_and_value_columns(all_rows: list[list[str]]) -> tuple[int, int, int]:
    """
    Locate the data start row and the (date_col, value_col) indices.

    BoJ CSV typically has 3-8 metadata rows before data. Date column is
    usually 0, value column is usually 1, but BoJ has been known to add
    leading blank columns or extra metadata columns.

    Returns (data_start_idx, date_col_idx, value_col_idx).
    """
    for i, row in enumerate(all_rows[:15]):
        if not row:
            continue
        for date_col in range(min(3, len(row))):
            parsed_date = _try_parse_boj_date(row[date_col])
            if parsed_date is None:
                continue
            for value_col in range(date_col + 1, len(row)):
                parsed_value = _try_parse_value(row[value_col])
                if parsed_value is not None:
                    return i, date_col, value_col

    raise ValueError(
        "BoJ CSV structure unexpected: no row with parseable (date, value) "
        "pair found in first 15 rows. Endpoint may have changed format."
    )


def fetch_tona_data(date_from: datetime, date_to: datetime) -> list[tuple[str, float]]:
    """
    Fetch TONA daily data from Bank of Japan.

    Returns list of (date_str_YYYYMMDD, rate_value) tuples sorted ascending.
    """
    params = build_request_params(date_from, date_to)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/csv, application/octet-stream",
    }

    response = requests.get(BOJ_URL, params=params, headers=headers, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()

    if response.encoding is None or response.encoding.lower() == "iso-8859-1":
        response.encoding = "shift_jis"

    text = response.text.lstrip("\ufeff")
    if not text:
        raise ValueError("BoJ response empty")

    all_rows = list(csv.reader(StringIO(text)))
    if not all_rows:
        raise ValueError("BoJ response has no parseable rows")

    data_start_idx, date_col, value_col = find_date_and_value_columns(all_rows)

    rows: list[tuple[str, float]] = []
    for raw_row in all_rows[data_start_idx:]:
        if len(raw_row) <= max(date_col, value_col):
            continue

        date_obj = _try_parse_boj_date(raw_row[date_col])
        if date_obj is None:
            continue

        if date_obj < date_from or date_obj > date_to:
            continue

        value = _try_parse_value(raw_row[value_col])
        if value is None:
            continue

        rows.append((date_obj.strftime("%Y%m%d"), value))

    rows.sort(key=lambda r: r[0])
    return rows


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
    print(f"BoJ series: {SERIES_CODE}")

    try:
        rows = fetch_tona_data(date_from, today)
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
        print("ERROR: No TONA rows returned from BoJ", file=sys.stderr)
        return 1

    write_csv(rows, OUTPUT_PATH)
    print(f"OK: Wrote {len(rows)} rows to {OUTPUT_PATH}")
    print(f"     Latest: {rows[-1][0]} = {rows[-1][1]:.4f}%")
    print(f"     Earliest: {rows[0][0]} = {rows[0][1]:.4f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
