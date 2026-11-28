# Brand

Everything about how the site looks lives here: colors, stage colors, fonts, names and logos. No other file types a color.

| File | What it is |
| --- | --- |
| `brand.json` | Colors (each with a note on where it's used), the six stage colors in order, fonts, the site's name and links, and the address-bar color. |
| `logo-primary.svg` | The primary logo (teal square), as plain shapes. The site's main logo since issue #42: headers, icons, share cards and downloads. |
| `logo.svg` | The secondary (framed) logo, as plain shapes. Kept for reference. |
| `logo-mark.svg`, `logo-mark-16.svg` | The "SR" favicon mark, drawn from the logo's own S and R; white on teal like the primary logo; the 16 px version has bigger letters. |
| `source/` | The original PNG and Affinity SVG files, for reference. |

## Changing the look

1. Edit `brand.json` (or replace the logo files).
2. Run `python3 tools/make_brand.py`. It rewrites `brand.css`, `site.webmanifest` and the `theme-color` line in each page.
3. If you changed stage colors, run `python3 build.py` so `projects.json` carries them too.
4. Run `python3 tests/run.py brand`. It fails if:
   - a page's text drops below 4.5:1 contrast, or a map dot below 3:1 on the paper or basemap
   - two stages get too close for people with color-vision differences
   - a color got typed somewhere outside `brand.json`
   - step 2 or 3 was skipped
5. Run the full tests (`python3 tests/run.py`) before pushing.

## Where the colors go

- **CSS:** `brand.css` defines `--ink`, `--paper`, `--stage-0` … `--stage-5`, the fonts (`--display`, `--deck`, `--sans`), the type scale (`--fs-*`, `--ls-*`), and three small icons. `styles.css` uses only these variables for color, font size and letter-spacing.
- **JavaScript:** `app.js` and `stats.js` read the same variables from the page at start-up. Stage colors also travel in `projects.json`.
- **Python** (share cards, sharing pages, icons, the build): `import branding`, then `branding.COLORS["ink"]`, `branding.STAGES`.

## The logos

The Affinity exports keep the words as live text in Helvetica Neue Condensed Black. Most visitors don't have that font, so `logo.svg` and `logo-primary.svg` were rebuilt as shapes by `tools/trace_logo.py`. Rendered back at 1000px, they match the PNGs on all but about 0.1% of pixels.

After any logo change, run `python3 tools/make_icons.py` to redraw the favicon and app icons.

If a designer exports SVGs with text converted to curves (Affinity: Layer › Convert to Curves), drop those in here instead.
