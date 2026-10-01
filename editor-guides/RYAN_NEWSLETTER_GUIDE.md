# Ryan's Newsletter Update Guide

You do not need to edit HTML, CSS, or JavaScript.

## Each week
1. In GitHub, open the `_ledger` folder.
2. Open `TEMPLATE.md`.
3. Click **Raw** or copy its contents.
4. Choose **Add file → Create new file**.
5. Name the file using the season and completed week, for example `2026-week4.md`.
6. Paste the template.
7. Change the information between the first two `---` lines.
8. Write the newsletter underneath using normal text and Markdown headings.
9. Click **Commit changes**.

GitHub Pages rebuilds the site automatically. The new issue appears in the archive without editing `ledger.html`.

## Formatting you can use
- `## Heading` = section heading
- `### Team Name` = smaller heading
- `**text**` = bold
- blank line = new paragraph
- `> text` = pull quote

Do not edit `data.js`; that belongs to the league-history editor.

## Template note
`_ledger/TEMPLATE.md` is marked `draft: true`, so it will never appear as a live newsletter issue. When creating a real issue, copy the template to a new filename and either delete `draft: true` or change it to `draft: false`.
