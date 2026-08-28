# Spokane in Progress

Tracking Spokane's housing progress. You keep the data in a Google Sheet; a build
step turns the sheet into the site.

## How it fits together

```
Google Sheet  ->  build.py  ->  data/projects.json  ->  the website
  (you edit)     (checks it)    (what the site reads)
```

You only ever touch the sheet.

## Files

| File | What it is |
| --- | --- |
| `data/projects.sample.csv` | The column layout, with seven fictional example projects. |
| `build.py` | Reads the sheet, checks the rows, writes `data/projects.json`. Python 3, nothing to install. |
| `index.html`, `styles.css`, `app.js` | The site itself. |
| `.github/workflows/build.yml` | Rebuilds the data every morning, and on demand. |

The sample projects are made up. Delete them once you have real ones.

## Setup

### 1. Make the sheet

Open `data/projects.sample.csv` in Google Sheets (File > Import). Keep the header
row exactly as it is — `build.py` looks for those column names.

Then **File > Share > Publish to web**, pick the sheet, choose **Comma-separated
values (.csv)**, publish, and copy the link.

Open `build.py` and paste the link between the quotes on the `SHEET_CSV_URL` line
near the top.

### 2. Check your work

```
python3 build.py
```

It reports rows it skipped, stages it did not recognize, coordinates outside
Spokane, duplicate ids, and images it left off for lack of permission.

To view the site locally:

```
python3 -m http.server 8000
```

Then open http://localhost:8000

### 3. Put it on GitHub

Create a repository and upload this folder. The web uploader is fine.

Under **Settings > Actions > General > Workflow permissions**, choose
**Read and write permissions** so the daily job can save updated data.

### 4. Publish it

In Cloudflare Pages, connect the repository:

- Build command: leave empty
- Build output directory: `/`

No build is needed on Cloudflare — the GitHub Action commits `data/projects.json`
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
They get written into `data/projects.json` and the website reads them from there,
so editing that one list changes the filters, the map dots, the header bar, and
the project pages together. Do not edit the fallback list in `app.js`.

After changing a stage name, update any rows in the sheet that used the old one,
then run `python3 build.py` — it will tell you which rows still need fixing.

## Before launch

- Replace the correction email in `index.html` (currently `hello@example.com`).
- Reword the footer disclaimer if you want it stronger or softer.
