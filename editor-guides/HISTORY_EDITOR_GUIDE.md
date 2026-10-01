# League History Editor Guide

The historical-statistics side of the Autocratic Association of Autism site is separate from The League Ledger.

## Career-record rule
Any career average, rate or leaderboard requires **3 completed seasons**. The site enforces this in `app.js` by separating managers with fewer than 3 seasons from the official career standings. Do not remove short-tenure managers from `data.js`; their history should remain preserved.

Single-week, single-game and single-season records do **not** require 3 seasons.

## Playoff scoring rule
This rule is important when updating historical data:

- Treat a playoff round as **one matchup**, regardless of whether ESPN spans it across one week or multiple weeks.
- For a **one-week playoff matchup**, the final score can participate in the normal weekly-score and one-week game leaderboards.
- For a **multi-week playoff matchup**, use **only ESPN's final full-matchup aggregate score**. Count the matchup once.
- Never reconstruct the individual weeks of a multi-week playoff matchup from player lineup totals for historical records.
- Multi-week aggregate scores must **not** be mixed into one-week highest/lowest scores, largest margins, closest games, highest combined scores, or projected-upset leaderboards.
- Preserve multi-week playoff results in the separate `multiWeekPlayoffs` archive so they remain part of league history.
- Career W-L counts each unique matchup once. Career scoring average/high/low uses only one-week matchups so the scoring scale remains comparable.
- If the league changes playoff format in a future season, determine the actual matchup length first. Do not assume every playoff round is one week or two weeks.

## Files you normally touch
- `data.js` — historical data displayed by the site
- historical site code/content as the archive becomes more personalized

## Files you normally do NOT touch
- `_ledger/` — Ryan's newsletter issues

## Current status
The history section is intentionally marked **early access** while the archive is being curated. Baseline stats and records are live. Planned additions include manager profiles, rivalries, custom awards, deeper historical context and other league-specific material.
