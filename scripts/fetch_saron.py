"""
fetch_saron.py
==============
Scraper for SARON (Swiss Average Rate Overnight) and SARON Compound Rates
(1M/3M/6M) from Swiss National Bank.

Source:   SNB Data Portal — cube `zirepo`
Endpoint: https://data.snb.ch/api/cube/zirepo/data/csv/en
Updated:  Daily (verified empirically 2026-05-29, PublishingDate 2026-05-21)

Why cube `zirepo` (not `zimoma`):
    The previous version of this scraper used cube `zimoma` (Money market rates),
    but that cube is published at END-OF-MONTH frequency, not daily. The cube
    `zirepo` is the SNB's daily SARON publication, with 9 series including the
    overnight SARON and the backward-looking Compound Rates introduced in 2017.

Series extracted (CSV dimension D0):
    H0  — Overnight (SARON), close of trading       → SARON.csv          (RFR for engine)
    H6  — SARON 1M Compound Rate                    → SARON_1M_COMPOUND.csv
    H7  — SARON 3M Compound Rate                    → SARON_3M_COMPOUND.csv
    H8  — SARON 6M Compound Rate                    → SARON_6M_COMPOUND.csv

Why Compound Rates also (not just overnight):
    The SARON Compound Rates are the CHF equivalent of SOFR 30/90/180-day
    Average (NY Fed), SONIA Compounded Index (BoE), €STR Compounded Average
    (ECB). They are the backward-looking compounded version of the overnight
    RFR, and are exactly the rates used by institutional XCCY basis swap
    quotes (Bloomberg/Refinitiv). Having them lets the engine compute the
    "clean" CIP basis using symmetric tenor RFR pairs (e.g. SARON_3M_Compound
    vs SOFR_90DAY_AVG), in addition to the sovereign-bills based proxy.

Format details:
    - CSV with `;` separator (NOT comma)
    - Values quoted with `"`
    - Preamble: CubeId line, PublishingDate line, blank line, then header
    - Header: "Date";"D0";"Value"
    - Long format: one row per (date, dimension) tuple
    - Values in PERCENT (e.g. -0.041183 = -0.041183%), consistent with other
      scrapers — NOT divided

Output:
    data/SARON.csv              — overnight SARON (used by engine as RFR_CHF)
    data/SARON_1M_COMPOUND.csv  — 1M compound (for Compound-Rates basis arch)
    data/SARON_3M_COMPOUND.csv  — 3M compound (primary symmetric tenor)
    data/SARON_6M_COMPOUND.csv  — 6M compound

License: SNB Data Portal public statistics. Used with attribution per SNB
         terms.
"""

import csv
import sys
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path

import requests


# Constants
SNB_URL = "https://data.snb.ch/api/cube/zirepo/data/csv/en"
HISTORY_YEARS = 5
TIMEOUT_SECONDS = 45
USER_AGENT = "xccy-g8/1.0 (https://github.com/sanderdayan1982/xccy-g8)"

# Dimension ID in the cube -> output filename
SERIES = {
    "H0": "SARON.csv",              # Overnight SARON (engine RFR_CHF)
    "H6": "SARON_1M_COMPOUND.csv",  # 1M Compound
    "H7": "SARON_3M_COMPOUND.csv",  # 3M Compound (primary symmetric tenor)
    "H8": "SARON_6M_COMPOUND.csv",  # 6M Compound
}

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data"

# Marker that precedes the data header row
HEADER_MARKER_PREFIX = '"Date"'


def fetch_saron(
    date_from: datetime,
    date_to: datetime,
) -> dict[str, list[tuple[str, float]]]:
    """
    Fetch SARON + Compound Rates from SNB cube `zirepo` in a single request.

    Returns dict mapping dimension ID (H0/H6/H7/H8) to sorted list of
    (date_str_YYYYMMDD, value_percent) tuples.
    """
    params = {
        "fromDate": date_from.strftime("%Y-%m-%d"),
        "toDate": date_to.strftime("%Y-%m-%d"),
    }
    headers = {"User-Agent": USER_AGENT, "Accept": "text/csv"}

    response = requests.get(SNB_URL, params=params, headers=headers, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()

    text = response.text
    if not text or "CubeId" not in text[:50]:
        raise ValueError(
            "SNB response empty or unexpected header. Cube `zirepo` may have changed."
        )

    lines = text.splitlines()

    # Locate the data header row (starts with "Date")
    data_start = None
    for i, line in enumerate(lines):
        if line.startswith(HEADER_MARKER_PREFIX):
            data_start = i
            break

    if data_start is None:
        raise ValueError(
            f"SNB CSV: header row starting with {HEADER_MARKER_PREFIX!r} not found"
        )

    # Parse with semicolon delimiter (SNB convention) and quote chars
    reader = csv.reader(lines[data_start:], delimiter=";", quotechar='"')
    header = next(reader)

    if len(header) < 3 or header[0] != "Date":
        raise ValueError(
            f"SNB CSV: expected header ['Date', 'D0', 'Value'], got: {header}"
        )

    # Group rows by dimension ID
    results: dict[str, list[tuple[str, float]]] = {sid: [] for sid in SERIES}

    for row in reader:
        if len(row) < 3:
            continue
        date_str, dim_id, value_str = row[0].strip(), row[1].strip(), row[2].strip()

        if dim_id not in SERIES:
            continue
        if not date_str or not value_str:
            continue

        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            continue

        try:
            value = float(value_str)
        except ValueError:
            continue

        # Store in YYYYMMDD format (consistent with all other scrapers)
        results[dim_id].append((date_obj.strftime("%Y%m%d"), value))

    for dim_id in results:
        results[dim_id].sort(key=lambda r: r[0])

    return results


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
    print(f"SNB cube: zirepo (daily)")
    print(f"Series: {list(SERIES.keys())} (H0=Overnight, H6/H7/H8=Compound 1M/3M/6M)")
    print()

    try:
        results = fetch_saron(date_from, today)
    except requests.HTTPError as exc:
        print(f"ERROR: SNB HTTP error: {exc}", file=sys.stderr)
        return 1
    except requests.RequestException as exc:
        print(f"ERROR: SNB network error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR: SARON fetch failed: {exc}", file=sys.stderr)
        return 1

    successes = 0
    failures = 0

    for dim_id, filename in SERIES.items():
        rows = results.get(dim_id, [])
        output_path = OUTPUT_DIR / filename

        if not rows:
            print(f"[{dim_id}] ERROR: No rows for {filename}", file=sys.stderr)
            failures += 1
            continue

        write_csv(rows, output_path)
        print(f"[{dim_id}] OK: Wrote {len(rows)} rows to {filename}")
        print(f"        Latest:   {rows[-1][0]} = {rows[-1][1]:.4f}%")
        print(f"        Earliest: {rows[0][0]} = {rows[0][1]:.4f}%")
        print()
        successes += 1

    print(f"Summary: {successes} OK, {failures} failed (of {len(SERIES)} total)")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
