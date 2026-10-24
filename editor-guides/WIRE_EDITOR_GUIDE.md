# AAA Insider — Around the League: quick publishing

Around the League is AAA Insider's default format. Each short story is an independent Markdown file with its own shareable URL, automatically included in the unified newest-first feed at `ledger.html`.

## Publish in 2 minutes

1. In GitHub, open `_wire/` on the **test** repository.
2. Choose **Add file → Create new file**. Name it `YYYY-MM-DD-a-short-slug.md`. (No spaces in the file name.)
3. Paste the template below. Change the title, date, category, summary, and paragraphs. Set `draft: false` **only when it is ready**.
4. Commit. Jekyll builds the feed and individual article automatically. Copy the new story link from `/wire/a-short-slug.html`.
5. After review and explicit approval, promote the same post to production.

```markdown
---
title: "Your headline"
date: 2026-10-23
format: wire
category: "League Politics"
author: "AAA Insider Newsroom"
summary: "A one-sentence teaser for the feed."
draft: true
---

The opening sentence should be newsworthy.

Two to four short paragraphs with the facts, the reaction, and one good punchline.

**AAA Insider finding:** Your closing line.
```

## Editorial guardrails

- Aim for 75–200 words; publish a long-form feature only when the story warrants it.
- Categories: Trades, League Politics, Newsroom, Waivers, Matchups, Breaking News, Investigations.
- Label rumors as unverified; seek responses on potentially damaging claims.
- Quotes must be accurate; don't convert a paraphrase into a purported direct quote.
- The full website article is the permanent record. GroupMe receives a short link and teaser; ESPN can feature the link.
- Report what matters; skip stale chatter rather than turning it into filler.
- To update a developing story, edit its existing file and add a dated update; keep the same URL. Create a second story for a truly separate development.
