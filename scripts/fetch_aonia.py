"""
fetch_aonia.py
==============
Scraper for AUD Overnight Index Average (AONIA / Interbank Overnight Cash Rate)
from Reserve Bank of Australia.

Source:   RBA Statistical Tables — F1.1 Money Market Daily
Endpoint: https://www.rba.gov.au/statistics/tables/csv/f1.1-data.csv
Format:   CSV with descriptive header rows (10 rows of metadata)
          then data rows in format: DATE, Value1, Value2, ...

Output:
    data/AONIA.csv  — AONIA historical series in OHLCV format

License: Data sourced from Reserve Bank of Australia public statistics.
         RBA retains all rights to source data.

Notes:
    RBA changes column ordering occasionally. This script identifies the
    Interbank Overnight Cash Rate column by NAME (not position) to be
    resilient to future format changes.
"""

import csv
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests


# Constants
RBA_URL = "https://www.rba.gov.au/statistics/tables/csv/f1.1-data.csv"
TARGET_COLUMN_HINTS = [
    "Interbank Overnight Cash Rate",
    "Cash Rate Target",
]
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "AONIA.csv"
HISTORY_YEARS = 5
TIMEOUT_SECONDS = 30
USER_AGENT = "xccy-g8/1.0 (https://github.com/sanderdayan1982/xccy-g8)"


def find_data_column_index(rows: list[list[str]]) -> tuple[int, int]:
    """
    Locate the data start row and the AONIA column index by inspecting the
    descriptive header rows. RBA CSVs have ~10 rows of metadata before data.

    Returns (data_start_row_index, aonia_column_index).
    Raises ValueError if structure cannot be parsed.
    """
    title_row_idx = None
    for i, row in enumerate(rows[:20]):
        if not row:
            continue
        joined = " | ".join(cell for cell in row if cell).lower()
        if any(hint.lower() in joined for hint in TARGET_COLUMN_HINTS):
            title_row_idx = i
            break

    if title_row_idx is None:
        raise ValueError(
            "RBA F1.1 CSV structure unexpected: target column hints not found "
            f"({TARGET_COLUMN_HINTS})"
        )

    title_row = rows[title_row_idx]
    aonia_col_idx = None
    for hint in TARGET_COLUMN_HINTS:
        for j, cell in enumerate(title_row):
            if cell and hint.lower() in cell.lower():
                aonia_col_idx = j
                break
        if aonia_col_idx is not None:
            break

    if aonia_col_idx is None:
        raise ValueError("RBA F1.1 CSV: AONIA column not found in title row")

    data_start_idx = None
    for i in range(title_row_idx + 1, min(title_row_idx + 15, len(rows))):
        row = rows[i]
        if not row or not row[0]:
            continue
        if _try_parse_rba_date(row[0]) is not None:
            data_start_idx = i
            break

    if data_start_idx is None:
        raise ValueError("RBA F1.1 CSV: no data rows found after title row")

    return data_start_idx, aonia_col_idx


def _try_parse_rba_date(s: str) -> datetime | None:
    """RBA date format is typically DD-Mon-YYYY (e.g. '15-May-2026')."""
    s = s.strip()
    for fmt in ("%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def fetch_aonia_data(date_from: datetime, date_to: datetime) -> list[tuple[str, float]]:
    """
    Fetch AONIA daily data from RBA Statistical Tables F1.1.

    Returns list of (date_str_YYYYMMDD, rate_value) tuples sorted ascending.
    """
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/csv",
    }

    response = requests.get(RBA_URL, headers=headers, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()

    text = response.text
    if not text or "RBA" not in text and "Reserve Bank" not in text:
        raise ValueError("RBA response empty or missing expected header content")

    all_rows = list(csv.reader(text.splitlines()))
    if not all_rows:
        raise ValueError("RBA response has no rows")

    data_start_idx, aonia_col_idx = find_data_column_index(all_rows)

    rows: list[tuple[str, float]] = []
    for raw_row in all_rows[data_start_idx:]:
        if len(raw_row) <= aonia_col_idx:
            continue

        date_obj = _try_parse_rba_date(raw_row[0])
        if date_obj is None:
            continue

        if date_obj < date_from or date_obj > date_to:
            continue

        value_raw = raw_row[aonia_col_idx].strip()
        if not value_raw:
            continue

        try:
            value = float(value_raw)
        except ValueError:
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

    print(f"Fetching AONIA from {date_from.date()} to {today.date()}")
    print(f"RBA Statistical Table: F1.1 Money Market Daily")

    try:
        rows = fetch_aonia_data(date_from, today)
    except requests.HTTPError as exc:
        print(f"ERROR: RBA HTTP error: {exc}", file=sys.stderr)
        return 1
    except requests.RequestException as exc:
        print(f"ERROR: RBA network error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR: AONIA fetch failed: {exc}", file=sys.stderr)
        return 1

    if not rows:
        print("ERROR: No AONIA rows returned from RBA", file=sys.stderr)
        return 1

    write_csv(rows, OUTPUT_PATH)
    print(f"OK: Wrote {len(rows)} rows to {OUTPUT_PATH}")
    print(f"     Latest: {rows[-1][0]} = {rows[-1][1]:.4f}%")
    print(f"     Earliest: {rows[0][0]} = {rows[0][1]:.4f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
