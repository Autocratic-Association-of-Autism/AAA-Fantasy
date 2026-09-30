# League History Editor Guide

The historical-statistics side of the site is separate from The League Ledger.

## Files you normally touch
- `data.js` — all history data displayed by the site

## Files you normally do NOT touch
- `_ledger/` — Ryan's newsletter issues
- `ledger.html` — newsletter archive layout
- `_layouts/` — page templates
- `styles.css` / `app.js` — site code

## Updating history
1. Generate the refreshed `data.js` from the league-history export/report using the same history workflow used to create the site.
2. In GitHub, open `data.js`.
3. Replace it with the newly generated version (or upload the replacement file).
4. Commit the change.
5. GitHub Pages republishes the site automatically.

This keeps newsletter editing and league-history editing independent.
