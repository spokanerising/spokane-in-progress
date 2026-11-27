# Tests

Headless-browser and build tests for Spokane in Progress. They serve a copy of
the site to Chrome with the network stubbed out (map library from an npm
copy, a blank base map, fake geocoders), so they run anywhere.

```
pip install playwright && python -m playwright install chromium
python3 tests/run.py              # everything
python3 tests/run.py filters      # files whose name contains "filters"
```

| File | Checks |
| --- | --- |
| `test_filters.py` | Every filter, live counts, pills, Near, map view, old links, phones. Uses made-up zoning/transit/density so every filter shows. |
| `test_real_data.py` | The real `projects.json`: unique ids, counts add up, outlines, project facts. |
| `test_site_facts.py` | `site_facts.py` and the outlines in `boundaries.py`, against fake servers. |
| `test_controls.py` | One look for every control: heights, corners, toggles, checkboxes, the focus ring, phones, and the unlinked `styleguide.html`. |
| `test_icons.py` | Icon buttons: labels, icons drawn, sizes, tooltips on hover and keyboard focus, the project bar's Copy link and Report a correction, the About chart download menu, phones. |
| `test_finishing.py` | Site icons and manifest, loading placeholders, the 404 page, the no-JavaScript note, printing a project. |
| `test_map_tools.py` | Scale bar, the Whole city button, skip links, and the map by keyboard: [ ] to step through projects, Enter to open, 0 for the whole city, Escape back to the row or map. |
| `test_share_toolkit.py` | `share.js`: share links, copying, downloads, CSV, notices; Copy link and the About CSV. |

GitHub runs them on every code push and after every data refresh
(`.github/workflows/tests.yml`). Screenshots land in `tests/.shots/`.
