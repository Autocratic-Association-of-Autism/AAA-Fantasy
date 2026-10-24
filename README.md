# Autocratic Association of Autism — League History + The League Ledger

This GitHub Pages site holds the rolling AAA Insider newsroom and the evolving historical archive. It can evolve into whatever you want, pending approval by the mod bros Ryan and Ryan.

## Current site status
- **AAA Insider:** live, publishing individual Around the League reports and long-form features whenever stories warrant it.
- **Historical archive:** early access. Baseline career stats, weekly records, game records and season history are live now; manager profiles, rivalries, custom awards, deeper storylines and other league-specific personalization will be added over time.

## Career-record eligibility
Career averages, rates and leaderboards require **at least 3 completed seasons**. Managers with fewer than 3 seasons remain visible in a separate limited-participation section.

## Playoff scoring policy
Playoff rounds are counted as matchups, not as reconstructed weekly scores. One-week playoff matchups can appear in the normal weekly and game records. If a playoff matchup spans multiple weeks, only ESPN's final aggregate result is used, the matchup is counted once, and that aggregate is stored in the separate multi-week playoff archive rather than competing with one-week records. Career W-L counts each matchup once; career scoring averages/highs/lows use one-week matchups only.

## Roles
### Ryan — newsletter editor
Ryan normally edits only `_ledger/`.

### League-history editor
The history editor normally updates `data.js` and develops the historical side of the site. See `editor-guides/HISTORY_EDITOR_GUIDE.md` before changing historical calculations.

A normal GitHub repository does not enforce per-folder write permissions; the separation is organizational.


## Current-season inclusion rule

Completed regular-season matchups from the active season belong in the archive immediately. They count toward career W-L, one-week scoring averages/highs/lows, and all one-week game/weekly leaderboards.

For 2026, this site currently includes completed results through Week 3. Ryan Mays's 55.62 in 2026 Week 2 is therefore his career one-week low and the current league record for lowest eligible weekly score.

An unfinished season does not count toward average finish or the minimum 3-completed-season career-record eligibility rule.

Future/unplayed matchups with 0 scores must never be imported as completed games.

## Rolling newsroom

AAA Insider publishes Around the League from `_wire/*.md` for short, standalone articles, and preserves long-form features under `_ledger/*.md`. Both appear in one newest-first feed at `ledger.html`; every story has a permanent, shareable URL. See `editor-guides/WIRE_EDITOR_GUIDE.md` for the copy/paste template and test-first workflow.
