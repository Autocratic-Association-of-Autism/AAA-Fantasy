# Fantasy League History + The League Ledger

This version is designed for multiple editors on GitHub Pages.

## Roles

### Ryan — newsletter editor
Ryan only edits files in `_ledger/`. Each issue is plain Markdown, not HTML. Creating a new `.md` issue automatically adds it to the Ledger archive and makes the newest issue appear on the homepage.

See `editor-guides/RYAN_NEWSLETTER_GUIDE.md`.

### League-history editor
The history editor updates `data.js`, which powers the career standings, records and season history. They do not need to touch newsletter files.

See `editor-guides/HISTORY_EDITOR_GUIDE.md`.

## Publishing
Host the repository with GitHub Pages. GitHub Pages processes the Jekyll collection in `_ledger` and republishes whenever either editor commits a change.

## Important
A normal GitHub repository does not enforce per-folder write permissions. Both collaborators can technically edit everything, but the files are intentionally separated so each person has a clear area to maintain.
