# Edits

Every Save in the site's editor adds one file here, in a `YYYY/MM/` folder.
The build applies them last, oldest first, so the daily rebuild never undoes an edit.
The rules are in `edits.py`.

- Files are never changed or deleted. To undo an edit, add a newer one.
- `set` changes fields. `unset` puts a field back to the automatic value.
- Your edits are permanent. The one exception: the city's records can still move a stage
  forward from the one you set (never back, never off Stalled).
- `"hidden": true` takes a project off the site.

```json
{
  "project": "city-b2404005bldc",
  "permits": ["B2404005BLDC"],
  "at": "2026-11-27T09:12:44Z",
  "by": "spokanerising@gmail.com",
  "set": { "units": 48, "status": "Approved" },
  "was": { "units": 44, "status": "Applied" },
  "unset": [],
  "note": "Confirmed with the developer"
}
```

Fields that can be edited: name, address, description, status, statusUpdated, projectType,
units, stories, sqft, parking, estCost, developer, architect, permitUrl, lat, lng,
imageUrl, imageCredit, imagePermission, docUrl, docLabel, sourceUrls, lastVerified, hidden.
