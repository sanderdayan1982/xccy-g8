"""
fetch_sonia.py
==============
Scraper for Sterling Overnight Index Average (SONIA) from Bank of England.

Source: Bank of England Interactive Database (IADB)
Series code: IUDSOIA (Daily Sterling Overnight Index Average)
Endpoint: https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp

Output: data/SONIA.csv in Pine Seeds format
        DATE,OPEN,HIGH,LOW,CLOSE,VOLUME
        YYYYMMDD,value,value,value,value,0

License: Data sourced from Bank of England public statistics.
         Bank of England retains all rights to source data.
"""

import csv
import sys
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import requests


# Constants
SERIES_CODE = "IUDSOIA"
BOE_URL = "https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "SONIA.csv"
HISTORY_YEARS = 5
TIMEOUT_SECONDS = 30
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def build_request_url(date_from: datetime, date_to: datetime) -> str:
    """Build BoE IADB query URL for SONIA series in CSV export mode."""
    params = {
        "csv.x": "yes",
        "Datefrom": date_from.strftime("%d/%b/%Y"),
        "Dateto": date_to.strftime("%d/%b/%Y"),
        "SeriesCodes": SERIES_CODE,
        "CSVF": "TN",
        "UsingCodes": "Y",
        "VPD": "Y",
        "VFD": "N",
    }
    return f"{BOE_URL}?{urlencode(params)}"


def fetch_sonia_csv(date_from: datetime, date_to: datetime) -> str:
    """Fetch SONIA CSV from Bank of England IADB."""
    url = build_request_url(date_from, date_to)
    print(f"Fetching SONIA from {date_from.date()} to {date_to.date()}")
    print(f"BoE IADB series: {SERIES_CODE}")

    headers = {"User-Agent": USER_AGENT}
    response = requests.get(url, headers=headers, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()

    text = response.text
    if not text or "DATE" not in text.upper():
        raise ValueError("BoE response empty or missing DATE header")

    return text


def parse_boe_csv(csv_text: str) -> list:
    """Parse BoE CSV response into list of (date, value) tuples."""
    rows = []
    lines = csv_text.strip().split("\n")

    # Skip header line "DATE,IUDSOIA"
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue

        parts = line.split(",")
        if len(parts) < 2:
            continue

        date_str = parts[0].strip()
        value_str = parts[1].strip()

        if not date_str or not value_str:
            continue

        try:
            # BoE format: "02 Jan 2026"
            date = datetime.strptime(date_str, "%d %b %Y")
            value = float(value_str)
            rows.append((date, value))
        except (ValueError, TypeError) as e:
            print(f"Warning: skipping malformed row '{line}': {e}")
            continue

    return rows


def write_pine_seeds_csv(rows: list, output_path: Path) -> None:
    """Write rows to Pine Seeds OHLCV format."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["DATE", "OPEN", "HIGH", "LOW", "CLOSE", "VOLUME"])

        for date, value in rows:
            date_str = date.strftime("%Y%m%d")
            # SONIA is a single value per day; use it for OHLC, volume = 0
            writer.writerow([date_str, value, value, value, value, 0])


def main() -> int:
    """Fetch SONIA and write to data/SONIA.csv."""
    date_to = datetime.utcnow()
    date_from = date_to - timedelta(days=HISTORY_YEARS * 365)

    try:
        csv_text = fetch_sonia_csv(date_from, date_to)
    except requests.exceptions.RequestException as e:
        print(f"ERROR: HTTP request failed: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    rows = parse_boe_csv(csv_text)
    if not rows:
        print("ERROR: No SONIA rows returned from BoE", file=sys.stderr)
        return 1

    write_pine_seeds_csv(rows, OUTPUT_PATH)
    print(f"OK: wrote {len(rows)} rows to {OUTPUT_PATH}")
    print(f"     range: {rows[0][0].date()} -> {rows[-1][0].date()}")
    print(f"     last value: {rows[-1][1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
