#!/usr/bin/env python3
"""
Reads the City of Spokane's weekly permit activity reports and saves the
housing-unit count for every building permit issued.

The city's GIS permit layer has no unit count. These weekly PDFs do, in a
column headed "# House" -- 1 for a house, 2 for a duplex, 12 for a 12-unit
apartment building, 0 for roofs, remodels and trade permits.

Run it with:   python3 permit_reports.py
Backfill with: python3 permit_reports.py --backfill-weeks 104

Needs one extra library:   pip install pdfplumber

Writes:
  data/permit-units.csv               one row per permit, newest report wins
  data/permit-reports/processed.json  which reports have been read
  data/permit-reports/sample-words.json  raw positions from the newest
                                         report's first page, for debugging
"""

import argparse
import csv
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone

try:
    import pdfplumber
except ImportError:
    sys.exit("pdfplumber is not installed. Run:  pip install pdfplumber")

INDEX_URL = "https://my.spokanecity.org/business/resources/"
REPORT_BASE = (
    "https://static.spokanecity.org/documents/business/statistics/"
    "daily-activity-report/{year}/daily-activity-report-{day}.pdf"
)
REPORT_LINK = re.compile(
    r"https://static\.spokanecity\.org/documents/business/statistics/"
    r"daily-activity-report/\d{4}/daily-activity-report-\d{4}-\d{2}-\d{2}\.pdf",
    re.IGNORECASE,
)

OUT_CSV = os.path.join("data", "permit-units.csv")
STATE_DIR = os.path.join("data", "permit-reports")
PROCESSED = os.path.join(STATE_DIR, "processed.json")
SAMPLE = os.path.join(STATE_DIR, "sample-words.json")

COLUMNS = [
    "permit", "issue_date", "status", "units", "valuation", "parcel",
    "address", "owner", "brief_description", "detailed_description",
    "contractor", "report_from", "report_to", "report_url",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; spokane-in-progress; "
        "+https://projects.spokanerising.com)"
    )
}

# B2604501BLDC, B26M0087PDEV ...
PERMIT_RE = re.compile(r"^[A-Z]\d{2}[A-Z0-9]\d{4}[A-Z]{3,5}$")
PARCEL_RE = re.compile(r"^\d{5}\.\d{4}$")
DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
MONEY_RE = re.compile(r"^\$[\d,]+(\.\d\d)?$")
MAILING_RE = re.compile(r",\s*[A-Z]{2}\s+\d{5}(-\d{4})?\b|\b\d{5}(-\d{4})?\s*$", re.IGNORECASE)
RANGE_RE = re.compile(r"From:?\s*(\d{1,2}/\d{1,2}/\d{4})\s*To:?\s*(\d{1,2}/\d{1,2}/\d{4})")


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def fetch(url, timeout=60):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def exists(url):
    request = urllib.request.Request(url, headers=HEADERS, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status == 200
    except urllib.error.HTTPError:
        return False


def links_from_index():
    """The city's resources page links the latest few weekly reports."""
    html = fetch(INDEX_URL).decode("utf-8", "replace")
    return sorted(set(REPORT_LINK.findall(html)))


def links_by_probing(weeks):
    """Older reports stay online but drop off the index page.

    File names don't follow a fixed weekday (the week ending Sunday 11/22
    was posted as 11-23), so every day in the window is tried.
    """
    found = []
    today = date.today()
    for back in range(weeks * 7):
        day = today - timedelta(days=back)
        url = REPORT_BASE.format(year=day.year, day=day.isoformat())
        if exists(url):
            found.append(url)
        time.sleep(0.1)
    return found


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def to_int(text):
    text = str(text or "").replace(",", "").replace("$", "").strip()
    try:
        return int(float(text))
    except ValueError:
        return None


def rows_of(words, tolerance=2.5):
    """Group words into visual lines by their top edge."""
    rows = []
    for word in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if rows and abs(rows[-1][0]["top"] - word["top"]) <= tolerance:
            rows[-1].append(word)
        else:
            rows.append([word])
    return [sorted(row, key=lambda w: w["x0"]) for row in rows]


def join(words):
    return " ".join(w["text"] for w in words).strip()


def find_columns(words):
    """Locate the column edges from the header on this page.

    Returns None when a page has no header (shouldn't happen, but a page that
    is all continuation text is skipped rather than guessed at).
    """
    def first(predicate):
        for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
            if predicate(w["text"]):
                return w
        return None

    house = first(lambda t: t == "House")
    issue = first(lambda t: t == "Issue")
    owner = first(lambda t: t == "Owner")
    brief = first(lambda t: t == "Brief")
    contractor = first(lambda t: t.startswith("Contractor"))
    valuation = first(lambda t: t == "Valuation")
    if not all([house, issue, owner, brief, contractor]):
        return None

    header_words = [
        w for w in words
        if w["top"] <= (valuation or house)["bottom"] + 16
        and w["text"] in {"Applicant", "Address"}
    ]
    header_bottom = max(
        [w["bottom"] for w in header_words] + [(valuation or house)["bottom"]]
    )
    return {
        "date": issue["x0"],
        "owner": owner["x0"],
        "brief": brief["x0"],
        "contractor": contractor["x0"],
        "right": max(house["x1"], (valuation or house)["x1"]),
        "header_bottom": header_bottom,
    }


def in_col(word, left, right):
    return left - 3 <= word["x0"] < right - 3


def parse_record(words, cols):
    """One permit: the lines from its permit number to the next one."""
    lines = rows_of(words)
    first_line = lines[0]
    top = first_line[0]["top"]

    # The status line carries the parcel number under "Issue Date".
    status_index = None
    for i, line in enumerate(lines[1:], start=1):
        if any(PARCEL_RE.match(w["text"]) for w in line):
            status_index = i
            break
    if status_index is None:
        # Some permits have no parcel; fall back to the second line.
        status_index = 1 if len(lines) > 1 else 0
    status_top = lines[status_index][0]["top"]

    # The applicant sits at the bottom: a name left-aligned with the permit
    # number and a mailing address ("..., SPOKANE, WA 99218") beside it. The
    # mailing address is what tells it apart from a status that wrapped onto
    # a second line ("Final" / "Inspection Done").
    def left_word(line):
        return any(w["x0"] < cols["date"] - 3 for w in line)

    def mailing(line):
        text = join([w for w in line if w["x0"] >= cols["owner"] - 3])
        return bool(MAILING_RE.search(text))

    applicant_index = len(lines)
    for i in range(status_index + 1, len(lines)):
        line = lines[i]
        if not left_word(line):
            continue
        name_only = all(w["x0"] < cols["owner"] - 3 for w in line)
        if mailing(line) or (name_only and i + 1 < len(lines) and mailing(lines[i + 1])):
            applicant_index = i
            break
    else:
        # No mailing address found: fall back to the run of left-aligned
        # lines at the very bottom.
        for i in range(len(lines) - 1, status_index, -1):
            if left_word(lines[i]):
                applicant_index = i
            elif not all(MONEY_RE.match(w["text"]) for w in lines[i]):
                break

    right_edge = cols["right"] - 20
    units = None
    for w in first_line:
        if w["x1"] >= right_edge and to_int(w["text"]) is not None and not w["text"].startswith("$"):
            units = to_int(w["text"])

    valuation = None
    for line in lines[status_index:applicant_index] or lines:
        for w in line:
            if w["x1"] >= right_edge and MONEY_RE.match(w["text"]):
                valuation = to_int(w["text"])
                break
        if valuation is not None:
            break

    top_block = [w for line in lines[:status_index] for w in line]
    middle_block = [w for line in lines[status_index:applicant_index] for w in line]

    permit = first_line[0]["text"]
    issue_date = next((w["text"] for w in first_line if DATE_RE.match(w["text"])), "")
    owner = [w for w in top_block if in_col(w, cols["owner"], cols["brief"])]
    brief = [w for w in top_block if in_col(w, cols["brief"], cols["contractor"])]
    contractor = [
        w for w in top_block
        if in_col(w, cols["contractor"], right_edge) and w["x1"] < right_edge
    ]
    status = [
        w for line in lines[status_index:applicant_index] for w in line
        if w["x0"] < cols["date"] - 3
    ]
    parcel = next((w["text"] for w in lines[status_index] if PARCEL_RE.match(w["text"])), "")
    address = [w for w in middle_block if in_col(w, cols["owner"], cols["brief"])]
    detail = [
        w for w in middle_block
        if in_col(w, cols["brief"], cols["contractor"] + 200)
        and not MONEY_RE.match(w["text"])
        and w["x1"] < right_edge
    ]

    return {
        "permit": permit,
        "issue_date": issue_date,
        "status": join(status),
        "units": units if units is not None else "",
        "valuation": valuation if valuation is not None else "",
        "parcel": parcel,
        "address": join(sorted(address, key=lambda w: (w["top"], w["x0"]))),
        "owner": join(sorted(owner, key=lambda w: (w["top"], w["x0"]))),
        "brief_description": join(sorted(brief, key=lambda w: (w["top"], w["x0"]))),
        "detailed_description": join(sorted(detail, key=lambda w: (w["top"], w["x0"]))),
        "contractor": join(sorted(contractor, key=lambda w: (w["top"], w["x0"]))),
        "_top": top,
    }


def parse_report(pdf_bytes):
    """Returns (records, info). info carries the date range and any totals."""
    records = []
    info = {"from": "", "to": "", "summary_new_units": None, "pages": 0}
    sample = None

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        info["pages"] = len(pdf.pages)
        all_text = []
        for page_number, page in enumerate(pdf.pages, start=1):
            words = page.extract_words(x_tolerance=1.5, y_tolerance=2, keep_blank_chars=False)
            text = page.extract_text() or ""
            all_text.append(text)
            if page_number == 1:
                sample = [
                    {k: (round(w[k], 1) if isinstance(w[k], float) else w[k])
                     for k in ("text", "x0", "x1", "top", "bottom")}
                    for w in words
                ]
            cols = find_columns(words)
            if not cols:
                continue
            body = [w for w in words if w["top"] > cols["header_bottom"] + 1]
            # Drop the page footer ("Page 3 of 31").
            body = [w for w in body if not re.match(r"^Page$", w["text"])]
            footer_tops = [w["top"] for w in words if w["text"] == "Page"]
            if footer_tops:
                body = [w for w in body if w["top"] < max(footer_tops) - 2]

            starts = sorted(
                (w for w in body if PERMIT_RE.match(w["text"]) and w["x0"] < cols["date"] - 3),
                key=lambda w: w["top"],
            )
            for i, start in enumerate(starts):
                end = starts[i + 1]["top"] - 1 if i + 1 < len(starts) else float("inf")
                chunk = [w for w in body if start["top"] - 1 <= w["top"] < end]
                records.append(parse_record(chunk, cols))

        joined = "\n".join(all_text)
        match = RANGE_RE.search(joined)
        if match:
            info["from"], info["to"] = match.group(1), match.group(2)
        summary = re.search(r"New Residential Units\s*:?\s*(\d+)", joined)
        if summary:
            info["summary_new_units"] = int(summary.group(1))

    info["sample"] = sample
    return records, info


# ---------------------------------------------------------------------------
# Saving
# ---------------------------------------------------------------------------

def keep(record):
    """Keep housing permits and commercial building permits; drop the rest.

    The report lists every roof, fence and water heater. Keeping them all
    would grow this file by ~50,000 rows a year for no benefit.
    """
    units = to_int(record.get("units"))
    return bool(units) or record["permit"].endswith("BLDC")


def load_existing():
    try:
        with open(OUT_CSV, encoding="utf-8", newline="") as handle:
            return {row["permit"]: row for row in csv.DictReader(handle)}
    except OSError:
        return {}


def save(rows):
    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    ordered = sorted(
        rows.values(),
        key=lambda r: (_sortable(r.get("issue_date")), r["permit"]),
        reverse=True,
    )
    with open(OUT_CSV, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(ordered)


def _sortable(us_date):
    try:
        return datetime.strptime(us_date, "%m/%d/%Y").date().isoformat()
    except (TypeError, ValueError):
        return ""


def load_processed():
    try:
        with open(PROCESSED, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--backfill-weeks", type=int, default=0,
                        help="also look for older reports this many weeks back")
    parser.add_argument("--reprocess", action="store_true",
                        help="read every report again, even ones already done")
    parser.add_argument("--file", action="append", default=[],
                        help="parse a local PDF instead of downloading (testing)")
    args = parser.parse_args()

    processed = {} if args.reprocess else load_processed()
    rows = load_existing()
    problems = []

    if args.file:
        sources = [(path, None) for path in args.file]
    else:
        try:
            urls = links_from_index()
        except Exception as error:
            sys.exit(f"Could not read the city's report index page: {error}")
        print(f"Index page lists {len(urls)} weekly report(s).")
        if args.backfill_weeks:
            print(f"Looking back {args.backfill_weeks} weeks for older reports...")
            urls = sorted(set(urls) | set(links_by_probing(args.backfill_weeks)))
            print(f"Found {len(urls)} report(s) in total.")
        sources = [(None, url) for url in urls if url not in processed]
        if not sources:
            print("No new reports. Nothing to do.")
            return

    newest_sample = None
    for path, url in sorted(sources, key=lambda s: s[1] or s[0]):
        name = url or path
        try:
            if path:
                with open(path, "rb") as handle:
                    pdf_bytes = handle.read()
            else:
                pdf_bytes = fetch(url)
            records, info = parse_report(pdf_bytes)
        except Exception as error:
            problems.append(f"{name}: could not read it ({error}). Will retry next run.")
            continue

        kept = [r for r in records if keep(r)]
        units_total = sum(to_int(r["units"]) or 0 for r in records)
        no_units = sum(1 for r in records if r["units"] == "")
        for record in kept:
            record.update(
                report_from=info["from"], report_to=info["to"], report_url=url or path
            )
            rows[record["permit"]] = record

        line = (
            f"{info['from'] or '?'} to {info['to'] or '?'}: {info['pages']} pages, "
            f"{len(records)} permits, {units_total} units, kept {len(kept)}"
        )
        print(line)
        if not records:
            problems.append(f"{name}: no permits found. The report layout may have changed.")
        if no_units:
            problems.append(f"{name}: {no_units} permit(s) had no readable unit count.")
        summary = info["summary_new_units"]
        if summary is not None and summary != units_total:
            # Not necessarily wrong: the city's total may count new buildings
            # only. Logged so a layout change can't slip by silently.
            problems.append(
                f"{name}: the report's own total says {summary} new units; "
                f"the permits add up to {units_total}."
            )

        if url:
            processed[url] = {
                "from": info["from"], "to": info["to"], "permits": len(records),
                "units": units_total, "summary_new_units": summary,
                "read_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        newest_sample = info["sample"]

    save(rows)
    os.makedirs(STATE_DIR, exist_ok=True)
    if not args.file:
        with open(PROCESSED, "w", encoding="utf-8") as handle:
            json.dump(processed, handle, indent=2, sort_keys=True)
    if newest_sample is not None:
        with open(SAMPLE, "w", encoding="utf-8") as handle:
            json.dump(newest_sample, handle, indent=0)

    housing = sum(1 for r in rows.values() if (to_int(r.get("units")) or 0) >= 2)
    print(f"\nSaved {len(rows)} permits to {OUT_CSV} ({housing} with 2+ units).")
    if problems:
        print(f"\n{len(problems)} thing(s) to look at:")
        for problem in problems:
            print(f"  - {problem}")


if __name__ == "__main__":
    main()
