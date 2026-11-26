"""Last-pass cleanup of text that comes straight from the city's records.

build.py runs `polish(projects)` just before it writes projects.json, so every
project, whatever its source, gets the same treatment. Names and descriptions
are only touched on projects the build added automatically (autoAdded): a name
or description typed into the sheet is left exactly as typed. Addresses get the
junk-stripping on every project, since the sheet's are usually clean anyway.

Each rule is small and does one thing, so a bad rule is easy to find and drop.
Standard library only.
"""

import re

AP_MONTHS = ["Jan.", "Feb.", "March", "April", "May", "June", "July", "Aug.",
             "Sept.", "Oct.", "Nov.", "Dec."]

PLEX = {"2": "Duplex", "3": "Triplex", "4": "Fourplex", "5": "Fiveplex", "6": "Sixplex",
        "8": "Eightplex"}

# Abbreviations in permit titles, spelled out. Word-bounded, case-sensitive
# where a lower-case match would hit real words.
NAME_WORDS = [
    (r"\bCOU\b", "Conversion"),            # change of use
    (r"\bMF\b", "Multifamily"),
    (r"\bBldgs\.?(?=\s|$)", "Buildings"),
    (r"\bBldg\.?(?=\s|$)", "Building"),
    (r"\bApts\.?(?=\s|$|\))", "Apartments"),
    (r"\bw/\s*", "with "),
    (r"\bMulti[- ]Family\b", "Multifamily"),
    (r"\bMixed Use\b", "Mixed-Use"),
]


def ap_date(iso):
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", iso or "")
    if not m:
        return iso
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return f"{AP_MONTHS[month - 1]} {day}, {year}"


def tidy_address(text):
    text = text or ""
    # "2111 W Ohio Ave Secondary Address For This Parce(l)" and similar notes.
    text = re.sub(r"\s*\bsecondary address\b.*$", "", text, flags=re.I)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip(" ,;&-")


def plural(word):
    return word if word.endswith("s") else word + "s"


def tidy_name(name, address, units):
    text = (name or "").strip()

    # "New 3 Unit Townhouse - 3199 E 10th" -> "3199 E 10th Ave Townhouses"
    m = re.match(r"^New\s+\d+\s*-?\s*Units?\s+(.+?)\s+-\s+.+$", text, flags=re.I)
    if m and address:
        kind = m.group(1).strip().title()
        text = f"{address} {plural(kind) if (units or 0) > 2 else kind}"

    for pattern, repl in NAME_WORDS:
        text = re.sub(pattern, repl, text)

    # "4-Plex" / "6-plex" -> "Fourplex" / "Sixplex"
    text = re.sub(r"\b(\d)-?[Pp]lex(es)?\b",
                  lambda m: PLEX.get(m.group(1), m.group(0)) + (m.group(2) or ""), text)

    return re.sub(r"\s{2,}", " ", text).strip()


def sentence(text):
    """One permit description as a tidy sentence."""
    text = (text or "").strip(" -/")
    if not text:
        return ""
    # Shouting: "NEW CONSTRUCTION FOR A SINGLE BUILDING 2 STORY- FOURPLEX"
    letters = re.sub(r"[^A-Za-z]", "", text)
    if letters and letters.isupper() and len(letters) > 8:
        text = text.lower()
        text = re.sub(r"\b(adu|sfr|llc)\b", lambda m: m.group(1).upper(), text)
    # "New 8 Bedroom New Duplex" -> "New 8 Bedroom Duplex"
    text = re.sub(r"^(New\b.*?)\s+New\s+", r"\1 ", text, flags=re.I)
    text = re.sub(r"(\w)-\s+(?=[A-Za-z])", r"\1 - ", text)        # "2 STORY- FOURPLEX"
    text = re.sub(r"\bSQ\.?\s?FT\b\.?", "sq. ft.", text, flags=re.I)
    text = re.sub(r"\s{2,}", " ", text).strip()
    text = text[0].upper() + text[1:]
    if not re.search(r"[.!?)]$", text):
        text += "."
    return text


def tidy_description(text):
    """City descriptions from several permits arrive joined with ' / '. Each part
    becomes its own sentence, and repeats are dropped."""
    parts, seen = [], set()
    for part in re.split(r"\s+/\s+", text or ""):
        s = sentence(part)
        if s and s.lower() not in seen:
            seen.add(s.lower())
            parts.append(s)
    return " ".join(parts)


def tidy_fields(fields):
    out = []
    for f in fields or []:
        if f.get("label") == "Source" and f.get("kind") == "text":
            f = dict(f, value=re.sub(r"\d{4}-\d{2}-\d{2}", lambda m: ap_date(m.group(0)), f["value"]))
        out.append(f)
    return out


def polish(projects):
    for p in projects:
        p["address"] = tidy_address(p.get("address"))
        p["fields"] = tidy_fields(p.get("fields"))
        if p.get("autoAdded"):
            p["name"] = tidy_name(p.get("name"), p["address"], p.get("units"))
            p["description"] = tidy_description(p.get("description"))
    return projects
