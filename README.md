# Spokane in Progress

Tracking Spokane's housing progress: <https://projects.spokanerising.com>

A daily build combines the city's permit records, the city's weekly and monthly
permit reports, a short hand-kept list of projects and your edits from the site
into one file, `projects.json`, which the website reads.

## How it fits together

```
city permit records (read every build) --------+
weekly permit reports (permit-reports/) -------+
data/projects/  (hand-curated, one file each) -+->  build.py  ->  projects.json  ->  the website
data/edits/     (your edits, applied last) ----+
```

- **GitHub** holds everything and runs the build (`.github/workflows/build.yml`) every
  morning around 5 a.m., whenever a permit report is uploaded, and whenever you save an
  edit on the site. The build commits the new data back to the repository.
- **Cloudflare Pages** publishes whatever is on `main`. There's no build step there.
  It also runs the editor's small server functions (`functions/`) and stores uploaded
  photos and PDFs (in an R2 bucket).
- **Tests** run on GitHub after every code change and every data refresh
  (`.github/workflows/tests.yml`). A failure marks the commit with a red X, and GitHub
  emails about it. It can't stop Cloudflare from publishing.

## Day to day

- **Edit a project:** sign in at `/admin/` (Cloudflare Access sends a one-time code to
  the editor's email), then use the pencil on any project. Each save is one new file in
  `data/edits/`, applied after everything else, so the daily rebuild never undoes it.
  The city's records can still move a stage forward, never back. History and Undo are
  in the editor. Rules: `edits.py` and `data/edits/README.md`.
- **Add a project:** in the editor, "Start from a permit" lists housing permits from the
  city's reports that aren't on the map. Adding one writes a file to `data/projects/`.
- **Upload the weekly permit report:** see `permit-reports/README.md`.
- **Things to look at:** each build lists them (projects it couldn't place, numbers that
  disagree with the city's, projects that left the map). The editor shows a project's
  own notes; `/admin/` shows the rest. They're also in `data/build-notes.json`.

## Files

| File | What it is |
| --- | --- |
| `build.py` | Reads everything, applies the edits, checks it, writes `projects.json` and the share pages. Python 3, nothing to install. |
| `city_records.py` | The city's permit records (its nightly permit map), read fresh every build. |
| `permit_reports.py` | Reads the weekly permit-report PDFs in `permit-reports/` for unit counts and job values. Needs `pdfplumber`; the GitHub job installs it. |
| `edits.py` | The rules for applying your edits. |
| `site_facts.py`, `boundaries.py` | Zoning, lot size, distance to frequent transit, neighborhood council and council district for each project, for the filters. Cached in `data/`. |
| `housing_types.py`, `milestones.py`, `display_tidy.py`, `pipeline_history.py` | Building type, timeline dates, tidier city text, and the daily pipeline count (`data/pipeline-history.csv`). |
| `pages.py`, `cards.py`, `pdf_thumbs.py` | Share pages (`p/`, `n/`, `d/`) and `sitemap.xml`, the share-card pictures, and thumbnails of linked PDFs. |
| `index.html`, `app.js`, `styles.css` | The map and list. |
| `stats.html` + `stats.js`, `about.html` + `about.js`, `glossary.html` + `glossary.js` | The Stats, About and Glossary pages (served at `/stats`, `/about`, `/glossary`). Glossary text lives in `glossary.json`. |
| `share.js`, `editor.js`, `admin/` | Sharing and downloads; the editor (loaded only when signed in); the editor's page. |
| `functions/` | Cloudflare functions for the editor: sign-in check, saving edits and new projects to GitHub, uploads, and serving uploaded files at `/media/`. |
| `brand/`, `branding.py`, `brand.css` | Colors, stage colors, fonts, names and logos, in one place. See `brand/README.md`. |
| `vendor/` | MapLibre, the map library, hosted with the site. See `vendor/README.md`. |
| `_headers` | How long browsers may keep each kind of file. |
| `data/` | Everything the build reads and writes besides `projects.json`: hand-curated projects, edits, caches, history, build notes. |
| `tests/` | Headless-browser and build tests. See `tests/README.md`. |
| `tools/` | One-off scripts: the logo and icon drawings, the site card, the old sheet import. |

## Check your work locally

```
python3 build.py                  # rebuild projects.json and report problems
python3 -m http.server 8000       # then open http://localhost:8000
python3 tests/run.py              # the tests (needs: pip install playwright && python3 -m playwright install chromium)
```

Locally, `/stats`, `/about` and `/glossary` don't work: Python's server only knows
`stats.html`. Cloudflare serves both, and the site links to the short form.

## Stages

Pre-Application (a pre-application conference held, no permit filed), Applied, Approved,
Under Construction, Complete, Stalled. Names and colors are defined once, in
`brand/brand.json`, and flow into `projects.json`, the filters, the map, the stage bar and
the project pages. After renaming a stage, update any files in `data/projects/` and
`data/edits/` that use the old name, then run `python3 build.py`, which lists what still
needs fixing.

## Hand-curated project files

`data/projects/` holds one file per project (they were rows of a Google Sheet until
Nov. 2026; the sheet is archived and no longer read). See `data/projects/README.md` for
the fields. In short:

- Leave a field empty and that line simply doesn't appear on the project page. No
  placeholders.
- `published: FALSE` keeps a project off the map, but it still claims its permits and
  parcels, which keeps the city's version off the map too.
- An image only appears when `image_permission` is `granted` or `public-record`.
- Link to the city's or the applicant's copy of a PDF rather than rehosting it.

Every project page ends with "This page displays available information at the time of
project entry."

Corrections: spokanerising@gmail.com. Produced by Anthony Gill, writer of Spokane Rising.
