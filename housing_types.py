"""Building type and middle-housing flag for every project.

build.py runs `classify_all(projects)` after display_tidy.polish(). Each
project gets:

  buildingType   one of TYPES below
  middleHousing  True for the types in MIDDLE_HOUSING

Middle housing follows Washington's definition (RCW 36.70A.030, from HB 1110):
buildings compatible in scale with single-family houses holding two or more
attached, stacked or clustered homes, including duplexes, triplexes,
fourplexes, fiveplexes, sixplexes, townhouses, stacked flats, courtyard
apartments and cottage housing. ADUs are not in that list.

How a type is chosen, first match wins:
  1. The sheet's Type column, if it holds one of the TYPES names exactly.
     (So you can always correct a project by typing e.g. "Townhomes".)
  2. Words in the name or description (conversion, assisted living, ADU,
     cottage, townhome, duplex, fourplex, eightplex ...).
  3. Units per building, from the unit count and the number of building
     permits: 2 units = duplex, 3-4 = triplex/fourplex, 5-6 = five/sixplex,
     7+ = apartments.
  4. "Apartments" / "lofts" / "podium" / "mixed-use" in the name.
  5. Otherwise "Not yet known".
Standard library only.
"""

import re

DUPLEX = "Duplex"
TRI_FOUR = "Triplex or fourplex"
FIVE_SIX = "Fiveplex or sixplex"
TOWNHOMES = "Townhomes"
COTTAGES = "Cottage housing"
APARTMENTS = "Apartments"
HOUSE_ADU = "House + ADU"
CONVERSION = "Conversion or addition"
GROUP = "Senior & group living"
UNKNOWN = "Not yet known"

TYPES = [DUPLEX, TRI_FOUR, FIVE_SIX, TOWNHOMES, COTTAGES,
         APARTMENTS, HOUSE_ADU, CONVERSION, GROUP, UNKNOWN]
MIDDLE_HOUSING = {DUPLEX, TRI_FOUR, FIVE_SIX, TOWNHOMES, COTTAGES}

BUILDING_PERMITS = {"Commercial Building New", "Residential Building Permit"}

WORD_RULES = [
    (CONVERSION, r"\bconver(sion|t|ted|ting)\b|\bchange of use\b|\bbasement units\b|\brestoration\b"),
    (GROUP, r"\bassisted living\b|\bmemory care\b|\bnursing\b|\bstudent\b|\bdorm(itory)?\b|\bSRO\b|\blodge\b|\bcongregate\b"),
    (HOUSE_ADU, r"\bADUs?\b|\baccessory dwelling"),
    (COTTAGES, r"\bcottages?\b"),
    (TOWNHOMES, r"\btown ?(home|house)s?\b|\browhouses?\b|\bzero lot\b"),
    (APARTMENTS, r"\b(seven|eight|nine|ten|[7-9]|1\d)-?plex(es)?\b|\beightplex"),
    (FIVE_SIX, r"\b(five|six|[56])-?plex(es)?\b|\bfiveplex|\bsixplex"),
    (TRI_FOUR, r"\b(tri|four|[34])-?plex(es)?\b|\btriplex|\bfourplex"),
    (DUPLEX, r"\bduplex(es)?\b"),
]

APARTMENT_WORDS = r"\bapartments?\b|\bapts\b|\blofts\b|\bpodium\b|\bmixed-use\b|\bflats\b"


def _sheet_type(project):
    for f in project.get("fields") or []:
        if f.get("label") == "Type" and f.get("value") in TYPES:
            return f["value"]
    return None


def _buildings(project):
    n = sum(1 for p in project.get("permits") or [] if p.get("type") in BUILDING_PERMITS)
    return max(n, 1)


def classify(project):
    override = _sheet_type(project)
    if override:
        return override

    text = f"{project.get('name', '')} {project.get('description', '')}"
    permit_types = {p.get("type") for p in project.get("permits") or []}
    if "Commercial Change of Use" in permit_types and "Commercial Building New" not in permit_types:
        return CONVERSION

    for kind, pattern in WORD_RULES:
        if re.search(pattern, text, flags=re.I):
            return kind

    units = project.get("units") or 0
    if units >= 2:
        if units == 2:
            return DUPLEX
        per = units / _buildings(project)
        if per <= 4:
            return TRI_FOUR
        if per <= 6:
            return FIVE_SIX
        return APARTMENTS

    if re.search(APARTMENT_WORDS, project.get("name", ""), flags=re.I):
        return APARTMENTS
    return UNKNOWN


def classify_all(projects):
    for p in projects:
        kind = classify(p)
        p["buildingType"] = kind
        p["buildingTypeInferred"] = _sheet_type(p) is None
        p["middleHousing"] = kind in MIDDLE_HOUSING
        p["projectType"] = kind  # kept for older code that reads projectType

        # The detail page shows the derived type in place of the sheet's
        # broad "Housing" / "Middle housing" label.
        label = kind + (" (middle housing)" if p["middleHousing"] else "")
        fields = [f for f in p.get("fields") or [] if f.get("label") != "Type"]
        at = next((i + 1 for i, f in enumerate(fields) if f.get("label") == "Stage"), 0)
        if kind != UNKNOWN:
            fields.insert(at, {"kind": "text", "label": "Building type", "value": label})
        p["fields"] = fields
    return projects
