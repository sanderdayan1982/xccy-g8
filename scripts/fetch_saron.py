"""
fetch_saron.py
==============
Scraper for Swiss Average Rate Overnight (SARON) from Swiss National Bank.

Source:   SNB data service (data.snb.ch)
Endpoint: https://data.snb.ch/api/cube/zimoma/data/json
Cube:     zimoma (Money market rates)
Filter:   D0 dimension = SARON (Swiss Average Rate Overnight)
Format:   JSON

Output:
    data/SARON.csv  — SARON historical series in OHLCV format

License: Data sourced from Swiss National Bank public statistics.
         SNB retains all rights to source data.
"""

import csv
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests


# Constants
SNB_URL = "https://data.snb.ch/api/cube/zimoma/data/json/en"
DIMENSION_FILTER = "SARON"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "SARON.csv"
HISTORY_YEARS = 5
TIMEOUT_SECONDS = 30
USER_AGENT = "xccy-g8/1.0 (https://github.com/sanderdayan1982/xccy-g8)"


def fetch_saron_data(date_from: datetime, date_to: datetime) -> list[tuple[str, float]]:
    """
    Fetch SARON daily data from SNB.

    SNB JSON structure:
        {
          "timeseries": [
            {
              "dimensionItem": ["SARON", ...],
              "values": [
                {"date": "YYYY-MM-DD", "value": X.XXXX},
                ...
              ]
            },
            ...
          ]
        }

    Returns list of (date_str_YYYYMMDD, rate_value) tuples sorted ascending.
    """
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }

    response = requests.get(SNB_URL, headers=headers, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()

    data = response.json()
    if "timeseries" not in data:
        raise ValueError("SNB response missing 'timeseries' key")

    saron_series = None
    for series in data["timeseries"]:
        dims = series.get("dimensionItem", [])
        if dims and dims[0] == DIMENSION_FILTER:
            saron_series = series
            break

    if saron_series is None:
        raise ValueError(f"SNB response has no series matching dimension '{DIMENSION_FILTER}'")

    rows: list[tuple[str, float]] = []
    for obs in saron_series.get("values", []):
        date_raw = obs.get("date")
        value_raw = obs.get("value")

        if date_raw is None or value_raw is None:
            continue

        try:
            date_obj = datetime.strptime(date_raw, "%Y-%m-%d")
            value = float(value_raw)
        except (ValueError, TypeError):
            continue

        if date_obj < date_from or date_obj > date_to:
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

    print(f"Fetching SARON from {date_from.date()} to {today.date()}")
    print(f"SNB cube: zimoma, dimension: {DIMENSION_FILTER}")

    try:
        rows = fetch_saron_data(date_from, today)
    except requests.HTTPError as exc:
        print(f"ERROR: SNB HTTP error: {exc}", file=sys.stderr)
        return 1
    except requests.RequestException as exc:
        print(f"ERROR: SNB network error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR: SARON fetch failed: {exc}", file=sys.stderr)
        return 1

    if not rows:
        print("ERROR: No SARON rows returned from SNB", file=sys.stderr)
        return 1

    write_csv(rows, OUTPUT_PATH)
    print(f"OK: Wrote {len(rows)} rows to {OUTPUT_PATH}")
    print(f"     Latest: {rows[-1][0]} = {rows[-1][1]:.4f}%")
    print(f"     Earliest: {rows[0][0]} = {rows[0][1]:.4f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
