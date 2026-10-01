# League History Editor Guide

The historical-statistics side of the Autocratic Association of Autism site is separate from The League Ledger.

## Career-record rule
Any career average, rate or leaderboard requires **3 completed seasons**. The site enforces this in `app.js` by separating managers with fewer than 3 seasons from the official career standings. Do not remove short-tenure managers from `data.js`; their history should remain preserved.

Single-week, single-game and single-season records do **not** require 3 seasons.

## Files you normally touch
- `data.js` — historical data displayed by the site
- historical site code/content as the archive becomes more personalized

## Files you normally do NOT touch
- `_ledger/` — Ryan's newsletter issues

## Current status
The history section is intentionally marked **early access** while the archive is being curated. Baseline stats and records are live. Planned additions include manager profiles, rivalries, custom awards, deeper historical context and other league-specific material.
