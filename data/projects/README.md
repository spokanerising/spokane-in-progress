# Hand-curated projects

One file per project. These were the rows of the Google Sheet until Nov. 2026
(imported by `tools/import_sheet.py`). The sheet is archived: changes typed there no
longer reach the site.

Each file has the sheet's columns: `name`, `permit_numbers` (separated by `;`),
`parcel_id`, `status`, `units`, `published`, and so on. `order` is the sheet's old row
order. A file with `published` set to `FALSE` stays off the map, but it still claims its
permits and parcels, which keeps the city's version of that project off the map too.

The build never rewrites these files. To change a project, use the editor on the site,
which saves to `data/edits/`.
