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
