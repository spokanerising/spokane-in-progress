"""One-time import: the Google Sheet's rows -> data/projects/<id>.json.

Since Nov. 2026 the hand-curated projects live in the repo, one file each,
instead of in the Google Sheet. This copies every row across exactly as the
sheet has it (every column, as text), so the site builds the same as before.

  python3 tools/import_sheet.py "<published CSV link>"
  python3 tools/import_sheet.py path/to/download.csv

Rows marked published = FALSE are copied too. They still matter: a hidden row
claims its permits and parcels, which keeps the city's version of that project
off the map.

"order" keeps the sheet's row order, which the build uses to break ties.
It refuses to run if data/projects/ already has files, so it can't overwrite
edits made since.
"""
import csv, io, json, os, re, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "data", "projects")


def slug(text):
    s = "".join(c if c.isalnum() else "-" for c in (text or "").lower()).strip("-")
    return re.sub(r"-{2,}", "-", s)


def file_id(row, line):
    """The file name. Same as the build's project id where there is one."""
    return row.get("id") or slug(row.get("name")) or f"row-{line}"


def read(source):
    if source.startswith("http"):
        with urllib.request.urlopen(source, timeout=30) as response:
            text = response.read().decode("utf-8")
    else:
        with open(source, encoding="utf-8") as handle:
            text = handle.read()
    return list(csv.DictReader(io.StringIO(text)))


def main(source):
    os.makedirs(OUT, exist_ok=True)
    if [f for f in os.listdir(OUT) if f.endswith(".json")]:
        print("data/projects/ already has project files. Nothing imported.")
        return
    rows = read(source)
    used = set()
    for offset, raw in enumerate(rows):
        row = {(k or "").strip(): (v or "").strip() for k, v in raw.items() if (k or "").strip()}
        if not any(row.values()):
            continue
        name = file_id(row, offset + 2)
        base, n = name, 2
        while name.lower() in used:
            name, n = f"{base}-{n}", n + 1
        used.add(name.lower())
        record = {"order": offset + 1}
        record.update(row)
        with open(os.path.join(OUT, f"{name}.json"), "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
    print(f"Imported {len(used)} row(s) into data/projects/.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
