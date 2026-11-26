# Weekly permit reports go here

Drop the City of Spokane's weekly **Daily Activity Report** PDFs into this folder. Each upload
starts a site rebuild that reads the new report, saves each building permit's housing-unit count
and job value to `data/permit-units.csv`, and fills in any blank **units** or **est_cost** cells
on the site.

## Each week

1. Go to <https://my.spokanecity.org/business/resources/>, open **Reports/Studies/Statistics →
   Building Permit Statistics**, and under **Weekly Activity Reports** click the newest date.
2. Save the PDF (keep the city's file name, like `daily-activity-report-2026-11-23.pdf`).
3. In this folder on GitHub, click **Add file → Upload files**, drag the PDF in, and click
   **Commit changes**.

The **Actions** tab shows the run. It takes about a minute.

## Good to know

- Uploading the same report twice is harmless. It's only read once.
- Order doesn't matter. If an older report is uploaded after a newer one, the newer status wins.
- Older reports for backfilling stay online at the same address pattern, e.g.
  `https://static.spokanecity.org/documents/business/statistics/daily-activity-report/2025/daily-activity-report-2025-08-31.pdf`.
  GitHub's uploader takes up to 100 files at once.
- Only the **weekly** report goes here. The monthly DSC permit report has a different layout.

## What gets published

Every issued permit with **2 or more new units** that isn't already in the sheet goes on the site
automatically. Permits that share a parcel or a project name ("Bethany Apartments - Bldg. A" and
"Bldg. B") become one project. Each gets a "Source: City of Spokane weekly permit report" line and
a link to the report.

- **To take one over** (fix the name, add a neighborhood, photos and so on): add a row to the sheet
  with its permit number(s) in `permit_numbers`. Your row replaces the automatic one on the next
  build. Leave `units` and `est_cost` blank to keep the city's numbers.
- **To hide one:** add a sheet row with its permit number and `published` set to `FALSE`.

The full list of these permits is in `data/housing-permits-not-on-site.csv`.
