# Tests

Headless-browser and build tests for Spokane in Progress. They serve a copy of
the site to Chrome with the network stubbed out (the map library from the
site's own copy in vendor/, a blank base map, fake geocoders), so they run
anywhere. Each file works in its own temporary copy of the site, so run.py
runs up to four at a time.

```
pip install playwright && python -m playwright install chromium
python3 tests/run.py              # everything
python3 tests/run.py filters      # files whose name contains "filters"
TEST_WORKERS=1 python3 tests/run.py   # one at a time
```

| File | Checks |
| --- | --- |
| `test_filters.py` | Every filter, live counts, pills, Near, map view, old links, phones. Uses made-up zoning/transit/density so every filter shows. |
| `test_real_data.py` | The real `projects.json`: unique ids, counts add up, outlines, project facts. |
| `test_map_layers.py` | The Layers panel: one shaded layer at a time, grouped outline checkboxes, the address bar (`layer=`, `lines=`), the key and credits, the hover card, satellite, saved map images with a layer legend, shared links, no `layers/` folder, phones (360 and 390 px). |
| `test_layers.py` | `layers.py`'s pure-Python parts: Census margins of error, MFTE terms, class breaks, 2010 populations on 2020 tracts. |
| `test_designations.py` | `designations.py`: historic district, MFTE area, OZ 2.0, QCT and tract tags from the layer files, holes, overlaps, missing or broken files. |
| `test_site_facts.py` | `site_facts.py` and the outlines in `boundaries.py`, against fake servers. |
| `test_controls.py` | One look for every control: heights, corners, toggles, checkboxes, the focus ring, phones, and the unlinked `styleguide.html`. |
| `test_icons.py` | Icon buttons: labels, icons drawn, sizes, tooltips on hover and keyboard focus, the project bar's Copy link and Report a correction, the Stats chart download menu, phones. |
| `test_finishing.py` | Site icons and manifest, loading placeholders, the 404 page, the no-JavaScript note, printing a project. |
| `test_map_tools.py` | Scale bar, the Whole city button, skip links, and the map by keyboard: [ ] to step through projects, Enter to open, 0 for the whole city, Escape back to the row or map. |
| `test_project_page.py` | The project page: kicker, standfirst, spec sections, the permits table, the satellite view, PDF thumbnails (`pdf_thumbs.py`, offline), the foot, links to a section, print, phones. |
| `test_build_resilience.py` | The build when a city service is down: monthly-report places remembered, last known location kept, projects leaving the map noted. |
| `test_links.py` | Internal links use /stats, /about, /glossary (no .html redirects), old project ids find their project, canonical tags, the sitemap, MapLibre from vendor/, `_headers`. |
| `test_edits.py` | `edits.py`: edits applied on top of the build: later wins, reset, stage moves forward only, a units disagreement noted only when the city's number changes, hide, permit-number fallback, unsafe links refused. |
| `test_functions.py` | The editor's Cloudflare functions in Node: sign-in token checks (forged, expired, wrong account), what Save commits, refused edits, uploads and serving them (fake R2), adding a project. Needs Node. |
| `test_editor.py` | The editor in a browser: pencil only when signed in, form values for every project, what Save sends, errors, Hide, Reset, uploads (shrinking, turning upright, PDFs), build notes, History and Undo, adding a project with a map pin, phones, `/admin/`. |
| `test_brand.py` | `brand/brand.json` is the only place colors are typed; `brand.css` and the manifest are current; logos are shapes, not text; text, map-dot and color-blind contrast; every page loads `brand.css`. |
| `test_share_toolkit.py` | `share.js`: share links, copying, downloads, CSV, notices; Copy link and the Stats CSV. |

GitHub runs them on every code push and after every data refresh
(`.github/workflows/tests.yml`). Screenshots land in `tests/.shots/`.
