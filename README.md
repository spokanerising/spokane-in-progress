# Spokane in Progress

Tracking Spokane's housing progress. A daily build combines hand-curated projects,
the city's permit records and your edits into the site.

## How it fits together

```
data/projects/  (hand-curated, one file each) --+
city permit records + permit reports -----------+->  build.py  ->  projects.json  ->  the website
data/edits/     (your edits, applied last) -----+
```

The hand-curated projects were rows of a Google Sheet until Nov. 2026. The sheet is
archived, and changes typed there no longer reach the site. Edits are applied last, so
the daily rebuild never undoes them (rules in `edits.py` and `data/edits/README.md`).

## Files

| File | What it is |
| --- | --- |
| `data/projects/` | Hand-curated projects, one JSON file each (the old sheet rows). |
| `data/edits/` | One file per edit made on the site. Never changed or deleted. |
| `build.py` | Reads the projects and city records, applies the edits, checks everything, writes `projects.json`. Python 3, nothing to install. |
| `edits.py` | The rules for applying edits. |
| `index.html`, `styles.css`, `app.js` | The site itself. |
| `.github/workflows/build.yml` | Rebuilds the data every morning, and on demand. |
| `site_facts.py` | Adds zoning, lot size (homes per acre) and distance to frequent transit to each project, for the filters. Caches in `data/parcel-acres.json`, `data/zoning-*.json`, `data/transit-*`. |
| `boundaries.py` | Neighborhood council and council district for each project, and `boundaries.geojson`, the outlines the map draws when you filter to one. |

## Setup

### 1. Check your work

```
python3 build.py
```

It reports projects it skipped, stages it did not recognize, coordinates outside
Spokane, duplicate ids, and images it left off for lack of permission.

To view the site locally:

```
python3 -m http.server 8000
```

Then open http://localhost:8000

### 2. Put it on GitHub

Create a repository and upload this folder. The web uploader is fine.

Under **Settings > Actions > General > Workflow permissions**, choose
**Read and write permissions** so the daily job can save updated data.

### 4. Publish it

In Cloudflare Pages, connect the repository:

- Build command: leave empty
- Build output directory: `/`

No build is needed on Cloudflare — the GitHub Action commits `projects.json`
to the repository, so the site is already static by the time it deploys.

## The columns

**Always fill in:** `published`, `name`, `address`, `lat`, `lng`, `status`,
`last_verified`.

- **published** — `TRUE` puts it on the site. `FALSE` keeps it as a draft.
- **lat / lng** — right-click the address in Google Maps and click the coordinates
  to copy them.
- **status** — one of: `Pre-Application`, `Applied`, `Approved`,
  `Under Construction`, `Complete`, `Stalled`.
  `Pre-Application` means a pre-application conference has been held but no
  permit application has been filed.
  Capitalisation and a few common variants are forgiven; anything genuinely
  unrecognised is flagged and shown as `Stalled` until you fix it.
- **last_verified** — when you last confirmed the project is where you say it is.
  Sort by this column to find what needs rechecking.
- **project_type** — Housing, Mixed-use, Office, Commercial, Industrial, Civic.
- **units, sqft, stories, parking, est_cost** — numbers only, no commas or dollar
  signs. The site formats them.
- **permit_url** — link to the permit application record.
- **permit_numbers**, **source_urls** — separate multiples with semicolons.

### Blank fields

Leave a cell empty and that row simply does not appear on the project page. There
is no placeholder and no explanation to write — a project at Pre-Application stage
just shows fewer rows than one under construction.

Every project page ends with a note saying the page shows the information
available when the project was entered, plus the `last_verified` date.

### Images and documents

- **image_url** — a rendering or photo. Only appears on the site when
  **image_permission** is `granted` or `public-record`. Other values (`asked`,
  `denied`, blank) keep it hidden, and `build.py` will tell you it skipped one.
- **image_credit** — who to credit. Shown under the image.
- **doc_url** / **doc_label** — a PDF, shown as a link button. Link to the City's
  or the applicant's copy rather than rehosting your own; linking is not
  republication.

## Changing the stages

The stage names and their colours are defined once, at the top of `build.py`.
They get written into `projects.json` and the website reads them from there,
so editing that one list changes the filters, the map dots, the header bar, and
the project pages together. Do not edit the fallback list in `app.js`.

After changing a stage name, update any files in `data/projects/` and `data/edits/`
that used the old one, then run `python3 build.py`. It will tell you which ones still
need fixing.

## Before launch

- Replace the correction email in `index.html` (currently `hello@example.com`).
- Reword the footer disclaimer if you want it stronger or softer.
