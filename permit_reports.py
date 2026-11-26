#!/usr/bin/env python3
"""
Reads the City of Spokane's weekly permit activity reports and saves the
housing-unit count for every building permit issued.

The city's GIS permit layer has no unit count. These weekly PDFs do, in a
column headed "# House" -- 1 for a house, 2 for a duplex, 12 for a 12-unit
apartment building, 0 for roofs, remodels and trade permits.

The city's file server blocks scripted downloads, so the PDFs are saved by
hand into the permit-reports/ folder (see permit-reports/README.md). Each
one is read once; uploading the same file again does nothing.

Run it with:   python3 permit_reports.py

Needs one extra library:   pip install pdfplumber

Writes:
  data/permit-units.csv               one row per permit, newest report wins
  data/permit-reports/processed.json  which reports have been read
  data/permit-reports/sample-words.json  raw positions from the newest
                                         report's first page, for debugging
"""

import argparse
import csv
import hashlib
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

INBOX = "permit-reports"
# Bump when the parser changes, and every uploaded report is read again.
PARSER_VERSION = 3
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
    links = sorted(set(REPORT_LINK.findall(html)))
    if not links:
        snippet = " ".join(html[:300].split())
        print(f"  Index page returned {len(html)} characters and no report links. Starts: {snippet}")
    return links


def diagnose(url):
    """Print exactly what the city's server sends back for one URL."""
    for method in ("HEAD", "GET"):
        request = urllib.request.Request(url, headers=HEADERS, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read(400) if method == "GET" else b""
                print(f"  {method} {response.status} {response.headers.get('Content-Type')} "
                      f"{body[:120]!r}")
        except urllib.error.HTTPError as error:
            print(f"  {method} HTTP {error.code} {error.reason} "
                  f"{error.read(200)!r} server={error.headers.get('Server')}")
        except Exception as error:
            print(f"  {method} failed: {error}")


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
        carry = None
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

            # A permit cut off by the page break continues at the top of this
            # page, above the first new permit number. Stitch it back onto the
            # previous page's last permit, shifted down so it reads in order.
            first_top = starts[0]["top"] if starts else float("inf")
            leading = [w for w in body if w["top"] < first_top - 1]
            if leading and carry is not None:
                shift = carry["bottom"] + 20
                moved = [dict(w, top=w["top"] + shift, bottom=w["bottom"] + shift) for w in leading]
                records[-1] = parse_record(carry["words"] + moved, carry["cols"])

            carry = None
            for i, start in enumerate(starts):
                end = starts[i + 1]["top"] - 1 if i + 1 < len(starts) else float("inf")
                chunk = [w for w in body if start["top"] - 1 <= w["top"] < end]
                records.append(parse_record(chunk, cols))
                if i + 1 == len(starts):
                    carry = {"words": chunk, "cols": cols,
                             "bottom": max(w["bottom"] for w in chunk)}

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


def report_date(us_date):
    try:
        return datetime.strptime(us_date, "%m/%d/%Y").date()
    except (TypeError, ValueError):
        return date.min


def inbox_files():
    """PDFs dropped into the permit-reports folder, oldest name first."""
    if not os.path.isdir(INBOX):
        return []
    return sorted(
        os.path.join(INBOX, name) for name in os.listdir(INBOX)
        if name.lower().endswith(".pdf")
    )


def fingerprint(pdf_bytes):
    return hashlib.sha256(pdf_bytes).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Monthly DSC permit reports (permit-reports/monthly/)
#
# The monthly report is a slide deck, but the city's spreadsheets ride along
# inside it as file attachments. Some tabs list projects with a permit or
# pre-development number and a unit count: largest projects issued, largest
# in plan review, significant PDEV/MFTE proposals. Every such table is read,
# whatever its tab is called, and saved to data/monthly-units.csv.
# ---------------------------------------------------------------------------

MONTHLY_INBOX = os.path.join(INBOX, "monthly")
MONTHLY_CSV = os.path.join("data", "monthly-units.csv")
MONTHLY_COLUMNS = ["key", "permits", "title", "address", "units", "valuation",
                   "approved", "table", "as_of", "report"]
PERMIT_CELL = re.compile(r"^([A-Z]\d{2}[A-Z0-9]\d{4})([A-Z]{3,5})?\s*(?:([+-])\s*(\d+))?", re.I)


def expand_permits(cell):
    """'B2515747+5' -> B2515747..B2515752; 'B2512924-9' -> ..24 to ..29;
    'B26M0031PDEV' -> itself. Returns the 8-character stems (or full IDs
    when a suffix like PDEV is written)."""
    text = str(cell or "").strip().upper()
    match = PERMIT_CELL.match(text)
    if not match:
        return []
    stem, suffix, sign, n = match.groups()
    if suffix and not sign:
        return [stem + suffix]
    head, tail = stem[:-4], int(stem[-4:])
    if sign == "+":
        last = tail + int(n)
    elif sign == "-":
        last = int(str(tail)[: -len(n)] + n) if len(n) < len(str(tail)) else int(n)
    else:
        last = tail
    if last < tail or last - tail > 60:
        last = tail
    return [f"{head}{i:04d}" for i in range(tail, last + 1)]


def attachments(pdf_bytes):
    import pikepdf
    with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            for annot in page.get("/Annots", []) or []:
                if annot.get("/Subtype") != "/FileAttachment":
                    continue
                spec = annot.get("/FS")
                if spec is None or "/EF" not in spec:
                    continue
                yield spec["/EF"]["/F"].read_bytes()


def monthly_tables(pdf_bytes):
    import openpyxl
    for blob in attachments(pdf_bytes):
        try:
            book = openpyxl.load_workbook(io.BytesIO(blob), data_only=True, read_only=True)
        except Exception:
            continue
        for sheet in book.worksheets:
            rows = [list(r) for r in sheet.iter_rows(values_only=True)]
            as_of = ""
            for r in rows:
                for i, c in enumerate(r):
                    if isinstance(c, str) and c.strip().lower().startswith("last update"):
                        later = [x for x in r[i + 1:] if x is not None]
                        if later and hasattr(later[0], "date"):
                            as_of = later[0].date().isoformat()
            header_at = cols = None
            for n, r in enumerate(rows):
                labels = [str(c or "").strip().lower() for c in r]
                permit = next((i for i, c in enumerate(labels) if re.search(r"permit|pdev|mfte", c)), None)
                units = next((i for i, c in enumerate(labels) if "units" in c), None)
                if permit is not None and units is not None:
                    header_at = n
                    cols = {
                        "permit": permit, "units": units,
                        "title": next((i for i, c in enumerate(labels) if "title" in c), None),
                        "address": next((i for i, c in enumerate(labels) if "address" in c), None),
                        "valuation": next((i for i, c in enumerate(labels) if "valuation" in c), None),
                    }
                    break
            if header_at is None:
                continue
            for r in rows[header_at + 1:]:
                cell = lambda k: r[cols[k]] if cols[k] is not None and cols[k] < len(r) else None
                if any(isinstance(c, str) and re.search(r"expired|withdrawn|cancel", c, re.I) for c in r):
                    continue
                permits = expand_permits(cell("permit"))
                units = cell("units")
                if not permits or not isinstance(units, (int, float)) or units <= 0:
                    continue
                value = cell("valuation")
                yield {
                    "key": permits[0],
                    "permits": ";".join(permits),
                    "title": str(cell("title") or "").replace("*", "").strip(),
                    "address": str(cell("address") or "").strip(),
                    "units": int(units),
                    "valuation": int(value) if isinstance(value, (int, float)) else "",
                    "approved": "*" in str(cell("title") or ""),
                    "table": sheet.title,
                    "as_of": as_of,
                }


def read_monthly(processed, problems):
    if not os.path.isdir(MONTHLY_INBOX):
        return 0
    try:
        with open(MONTHLY_CSV, encoding="utf-8", newline="") as handle:
            saved = {r["key"]: r for r in csv.DictReader(handle)}
    except OSError:
        saved = {}
    read = 0
    for name in sorted(os.listdir(MONTHLY_INBOX)):
        if not name.lower().endswith(".pdf"):
            continue
        path = os.path.join(MONTHLY_INBOX, name)
        with open(path, "rb") as handle:
            pdf_bytes = handle.read()
        key = f"monthly/{name}:{fingerprint(pdf_bytes)}:v{PARSER_VERSION}"
        if key in processed:
            continue
        try:
            rows = list(monthly_tables(pdf_bytes))
        except Exception as error:
            problems.append(f"{path}: could not read its attached spreadsheets ({error}).")
            continue
        if not rows:
            problems.append(f"{path}: no project tables with permit numbers and units found.")
        month = re.search(r"(\d{4}-\d{2})", name)
        for row in rows:
            row["report"] = name
            row["as_of"] = row["as_of"] or (month.group(1) + "-01" if month else "")
            old = saved.get(row["key"])
            if old and old.get("as_of", "") > row["as_of"]:
                continue        # an older report uploaded later doesn't win
            saved[row["key"]] = row
        processed[key] = {"rows": len(rows), "read_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        print(f"{name}: {len(rows)} projects with unit counts")
        read += 1
    if read:
        os.makedirs(os.path.dirname(MONTHLY_CSV), exist_ok=True)
        with open(MONTHLY_CSV, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=MONTHLY_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(sorted(saved.values(), key=lambda r: -int(r["units"])))
    return read


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--fetch", action="store_true",
                        help="download from the city's website instead of reading the "
                             "permit-reports folder (blocked for scripts as of Nov 2026)")
    parser.add_argument("--backfill-weeks", type=int, default=0,
                        help="with --fetch, also look for older reports this many weeks back")
    parser.add_argument("--reprocess", action="store_true",
                        help="read every report again, even ones already done")
    parser.add_argument("--file", action="append", default=[],
                        help="parse one local PDF (testing)")
    args = parser.parse_args()

    processed = {} if args.reprocess else load_processed()
    rows = load_existing()
    problems = []

    # Each source is (label, loader). Loaders return the PDF's bytes.
    sources = []
    if args.file:
        sources = [(path, lambda p=path: open(p, "rb").read()) for path in args.file]
    elif args.fetch:
        try:
            urls = links_from_index()
        except Exception as error:
            sys.exit(f"Could not read the city's report index page: {error}")
        print(f"Index page lists {len(urls)} weekly report(s).")
        if not urls:
            known = REPORT_BASE.format(year=2026, day="2026-11-23")
            print(f"Checking a report known to exist: {known}")
            diagnose(known)
        if args.backfill_weeks:
            print(f"Looking back {args.backfill_weeks} weeks for older reports...")
            urls = sorted(set(urls) | set(links_by_probing(args.backfill_weeks)))
        sources = [(url, lambda u=url: fetch(u)) for url in urls if url not in processed]
    else:
        files = inbox_files()
        print(f"{len(files)} PDF(s) in {INBOX}/.")
        for path in files:
            sources.append((path, lambda p=path: open(p, "rb").read()))

    newest_sample = None
    newest_to = date.min
    read_count = 0
    for label, load in sources:
        try:
            pdf_bytes = load()
        except Exception as error:
            problems.append(f"{label}: could not open it ({error}).")
            continue
        key = (label if args.fetch else f"{os.path.basename(label)}:{fingerprint(pdf_bytes)}") + f":v{PARSER_VERSION}"
        if key in processed and not args.file:
            continue
        try:
            records, info = parse_report(pdf_bytes)
        except Exception as error:
            problems.append(
                f"{label}: could not read it as a permit report ({error}). "
                f"Is it the weekly Daily Activity Report PDF?"
            )
            continue
        read_count += 1

        this_to = report_date(info["to"])
        kept = [r for r in records if keep(r)]
        # Demolitions carry negative units (-1 for a house torn down). The
        # city's "New Residential Units" total counts additions only.
        units_total = sum(max(to_int(r["units"]) or 0, 0) for r in records)
        no_units = sum(1 for r in records if r["units"] == "")
        for record in kept:
            record.update(report_from=info["from"], report_to=info["to"], report_url=label)
            existing = rows.get(record["permit"])
            # A newer report wins, so uploading an old one later can't roll a
            # permit's status backwards.
            if existing and report_date(existing.get("report_to")) > this_to:
                continue
            rows[record["permit"]] = record

        print(
            f"{os.path.basename(label)}: {info['from'] or '?'} to {info['to'] or '?'}, "
            f"{info['pages']} pages, {len(records)} permits, {units_total} new units, kept {len(kept)}"
        )
        if not records:
            problems.append(
                f"{label}: no permits found. Either it isn't the weekly Daily Activity "
                f"Report, or the city changed the layout."
            )
        if no_units:
            problems.append(f"{label}: {no_units} permit(s) had no readable unit count.")
        summary = info["summary_new_units"]
        if summary is not None and summary != units_total:
            problems.append(
                f"{label}: the report's own total says {summary} new units; "
                f"the permits add up to {units_total}."
            )

        if not args.file:
            processed[key] = {
                "from": info["from"], "to": info["to"], "permits": len(records),
                "units": units_total, "summary_new_units": summary,
                "read_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        if this_to >= newest_to:
            newest_to = this_to
            newest_sample = info["sample"]

    if not args.file and not args.fetch:
        if read_monthly(processed, problems):
            os.makedirs(STATE_DIR, exist_ok=True)
            with open(PROCESSED, "w", encoding="utf-8") as handle:
                json.dump(processed, handle, indent=2, sort_keys=True)

    if not read_count:
        print("No new weekly reports to read.")
        for problem in problems:
            print(f"  - {problem}")
        return

    save(rows)
    os.makedirs(STATE_DIR, exist_ok=True)
    if not args.file:
        with open(PROCESSED, "w", encoding="utf-8") as handle:
            json.dump(processed, handle, indent=2, sort_keys=True)
    if newest_sample is not None:
        with open(SAMPLE, "w", encoding="utf-8") as handle:
            json.dump(newest_sample, handle, indent=0)

    housing = sum(1 for r in rows.values() if (to_int(r.get("units")) or 0) >= 2)
    print(f"\nRead {read_count} report(s). {OUT_CSV} now has {len(rows)} permits "
          f"({housing} with 2+ units).")
    if problems:
        print(f"\n{len(problems)} thing(s) to look at:")
        for problem in problems:
            print(f"  - {problem}")


if __name__ == "__main__":
    main()
