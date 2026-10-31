# AAA Fantasy Forecast Engine (v6 experimental workload track, 2026)

The league's existing ESPN Fantasy Export workflow supplies raw data. This engine **actually executes** under `.github/workflows/aaa-forecast.yml` after successful ESPN exports and on manual dispatches. No ESPN login details are copied into forecast artifacts; GitHub's `GITHUB_TOKEN` is used to read the existing export artifact.

## New in v6: live opportunity model, kept separate from baseline

- `forecast_output/forecast.json` continues to contain the proven v5 statistical scoring baseline and league matchup simulations; no previous model is silently overwritten.
- `forecast_output/workload_forecast.json` downloads the public [nflverse player-week 2026 statistics](https://github.com/nflverse/nflverse-data/releases/tag/stats_player) during each GitHub Actions forecast. It computes **independent expected carries, targets, catches, rushing/receiving yards, touchdowns, QB attempts and interceptions** from prior completed games only.
- Volume is a **provisional**, documented 55% recent three-game and 45% season average (35% recent for shorter histories). Catch/yard/TD rates are smoothed with published prior assumptions in `workload.py`. It does **not** copy ESPN projected points. All outputs link their source URI, fetch timestamp, SHA256, eligible observed weeks, and per-player fallback reason.
- The workload report recomputes legal lineups for all ten managers, obeys kickoff locks, and incorporates already-completed games as ESPN actual points when kickoff occurred over eight hours earlier. These are experimental **shadow recommendations** until prospective calibration supports replacing the baseline.
- A paired, strictly chronological Weeks 5–last-complete-week MAE comparison is reported on the same roster-sampled observations. This historical comparison is exploratory, *not* a sealed holdout or a claim of calibrated game win odds.
- If nflverse is missing or stale, report status is `BLOCKED_WORKLOAD_DATA_UNAVAILABLE` and the existing baseline remains intact. Missing individual statistics use clearly labeled `BASELINE_FALLBACK_MISSING_OPPORTUNITY_DATA`; K and D/ST deliberately retain baseline estimates.
- **Not available yet:** verified NFL offensive snap percentages, individual routes run, injury-adjusted snap limits, verified team depth-chart changes, opponent/OL/weather adjustments, and calibrated opportunity distributions. The code flags limited histories and missed games but does not assign injury probabilities or silently pretend to have those inputs.
- Public stats source: nflverse (CC BY 4.0). No member identities or raw private league export are committed to the public repository. The files are GitHub Actions artifacts.

Run the export then the forecast workflow; download the `AAA-Forecast-Validation-...` artifact to compare `forecast.json` with `workload_forecast.json`. The report is *informational* until subsequent prospective holdouts demonstrate an improvement in lineup decisions.

## v7: observed context and genuine prospective scorecards

**Observed pregame context (shadow only):** `contextual.py` reads nflverse's 2026 [offensive snap counts](https://github.com/nflverse/nflverse-data/releases/tag/snap_counts) and player-week records, frozen at the last completed week. Each player's report now includes a three-game offensive snap trend, opponent positional fantasy-points-allowed snapshot (when nflverse supplies opponent identity), and a team QB sacks-suffered-per-dropback proxy. All come from games completed before the target week, with source SHA256 / fetch provenance. These values are **descriptive, not unvalidated mean multipliers**: recent targets and carries already reflect much of the same role change, and applying an arbitrary additional percentage could double-count it. Missing or ambiguous feeds are explicitly marked.

**Verified teammate reports:** Optional `FORECAST_CONTEXT_FILE` input may include `verified_teammate_updates`, each containing `nfl_team`, `name`, `status`, HTTPS `source_url`, and timezone-aware `as_of`. Entries dated after the forecast are rejected; unverified claims do not become automatic role projections. This is **not** an unattended official injury-feed integration. Game-day inactive checks remain necessary.

**Unresolved inputs:** Route participation remains `NO_VERIFIED_ROUTE_FEED`. The QB sack-rate proxy measures all contributing factors, including scheme and QB decisions; it is **not** an independently validated offensive-line blocking grade, so no causal OL adjustment is made. Opponent allowance is not a causal defensive-strength adjustment. Weather and injury-induced role redistribution are also not validated. Do not treat a named input as modeled when it has only a warning or metadata field.

**Prospective scorecard:** Each successful ESPN export triggers `prospective.py`, which reviews previous archived GitHub Actions artifacts. It compares frozen baseline and workload PPR predictions **only when their original timestamp precedes each player's kickoff**, then records paired MAE. When a *whole* legal lineup was selected before any of its players kicked off, it also compares actual starter points and hindsight regret under the **same** observed outcomes. Forecasts created after Thursday kickoff cannot claim Thursday as a pregame prediction. No 2026 Week 1–7 backfill is labeled prospective; the first archived v6 opportunity forecast was made in Week 8. The scorecard will be pending until a completed Week 8 can be checked with an ESPN export in Week 9.

The `AAA-Forecast-Validation-...` Actions artifact contains `forecast.json`, `workload_forecast.json`, `prospective_scorecard.json`, and the verified kickoff schedule. A temporary GitHub artifact-download failure produces a clearly labeled pending or blocked scorecard without promoting the workload model or rewriting the baseline. **No model auto-promotion**: first require materially more prospective paired observations and lineup results, then independently review win rates, decision regret, uncertainty coverage and calibration before making a change.

## v8: live NFL injury reporting and route-source guardrails

- Every Actions forecast also attempts to retrieve the 2026 nflverse **weekly NFL injury-report feed**, including game-status designation, practice participation, primary injury and original modified timestamp. Data download is hashed and source-attributed. The feed updates daily, so it is **not the official game-day inactive list**. A missing row explicitly means *unknown/not reported*, never healthy.
- Match only the **target NFL week**, exact team and normalized player name. Future-dated records are excluded where the source provides an unambiguous timezone-aware modification timestamp. Unverified timestamps remain marked as unverified. Out-of-sync ESPN versus source `OUT` designations raise a mandatory official-inactive-review flag.
- Teammates listed as OUT/DOUBTFUL/QUESTIONABLE are visible as *observations* on the player's team. We do **not** distribute absent-player targets or carries with an arbitrary multiplier.
- Verified 2026 route participation is **not** available in nflverse during the season; participation exports are released after the postseason. Instead, an optional context manifest may add manually sourced `verified_route_reports` with player name, NFL team, completed week, routes run, team dropbacks, HTTPS source URL and timezone-aware observation date. Reports after the forecast or from uncompleted weeks are rejected. Route rates are informational and never invented or applied as a scoring multiplier.
- The already implemented team QB sack-rate indicator remains a **pass-protection proxy**, not an independent offensive-line grade. The engine will not label or promote it as a validated points adjustment.
- The previously implemented `prospective_scorecard.json` continues to evaluate immutable pregame artifacts after games finish. Injury and route annotations are experimental; promote a new point model only after prospective samples establish improved accuracy **and** decision regret.

Example optional route report (part of `FORECAST_CONTEXT_FILE`, alongside its normal `as_of` and `sources`):
```json
{
  "as_of": "2026-10-30T16:00:00Z",
  "sources": ["https://example.org/verified-charting"],
  "verified_route_reports": [
    {
      "name": "Example WR",
      "nfl_team": "CHI",
      "week": 7,
      "routes_run": 30,
      "team_dropbacks": 42,
      "source_url": "https://example.org/verified-charting",
      "as_of": "2026-10-27T12:00:00Z"
    }
  ]
}
```
This sample is **illustrative**, not an actual player report.

## v9: team-level scouting and all-position game-environment shadow forecasts

**Permanent integration:** Every AAA forecast now downloads the [nflverse play-by-play releases](https://github.com/nflverse/nflverse-data/releases/tag/pbp) for the active NFL season, verifies the source SHA256 and timestamp, and builds numerical matchup briefs from *completed prior weeks only*. The preview is computed for both sides of every scheduled NFL game, including games involving every rostered QB, RB, WR, TE, D/ST and K.

The verified context includes:
- **Game environment:** each side's observed plays/game, pass/run split, third-down conversion, red-zone snaps, field-goal attempts, QB dropbacks, and historical offensive EPA by pass and run.
- **Trenches:** team's sacks allowed per dropback and the opposing defense's sack rate, plus QB hits if the feed provides them; these are pressure **proxies**, not actual pass-block/run-block win rates or individual lineman grades.
- **Receiving and coverage:** observed team target depth, air yards and yards after catch, plus the already sourced player's target/carry history, snap shares and opponent position-level scoring. The standard PBP **does not contain verified current-season coverage assignment, man/zone identity or player-versus-specific-corner matching**. Those fields explicitly return unavailable, rather than invented values.
- **Injuries:** both offenses' and defenses' reported questionable, doubtful and out players, from separately sourced weekly injury reports; these do not confirm official gameday inactive status or automatically redistribute targets.
- **Opponent's offense:** opponent offensive pace, passing efficiency and run/pass tendency, as game-script context. This is not a betting line, implied total, predicted score or guaranteed number of plays.
- **Weather and rivalry:** missing weather reports and unvalidated rivalry coefficients remain labeled unavailable/unmodeled rather than baked into point estimates.

**Position-specific scenario layer:** `workload_forecast.json` includes `game_environment.matchups` and `player_projections[].position_game_script_scenario`. A separate **shadow** lineup, `game_environment_shadow_best`, uses legal roster slots, actual completed-game locks and bounded volume scenarios: QB pass attempt/yard/TD opportunity and sack exposure; RB rush and target opportunities; WR and TE route-proxy target volume and yards; D/ST observed opponent turnovers and sacks; K field-goal opportunities. DST and K modifiers are explicitly illustrative, not a fully derived point model. The official baseline and workload lineup recommendations **are not changed by these heuristic multipliers**.

**Historical checks:** `game_environment_backtest.json` compares the original baseline, original workload and v9 matchup scenario against the same week-specific archived ESPN roster (Weeks 5–most recently completed). The historical AAA cross-season workflow also runs the v9 comparison on 2024 and 2025 ESPN rosters. For a player in target week W, only PBP games from weeks strictly earlier than W may affect features. Opponent identity is known schedule context and does not supply result statistics. These are still post-hoc model evaluations and do **not** authorize automatic promotion: only prospective, timestamped pre-kickoff predictions and a material lineup-regret/accuracy gain would justify that.

If the current season PBP feed is unavailable, malformed or stale, `game_environment.status` reports a blocked reason while the v5 validated baseline and v6 workload track remain available. No external analyst opinion, free-form chat scouting or fabricated betting line can silently change the scoring mean.

## Validated and unvalidated parts

- **Independently time-split tested:** Per-player *scoring baseline* from previous completed weeks. Train/select hyperparameters on Weeks 2–4, hold out Weeks 5–6, then deploy the frozen hyperparameters to future weeks. Across 265 held-out player-weeks, MAE=6.2293 PPR points and empirical interval coverage is approximately 77.4% for 80% and 89.1% for 90% intervals.
- **Not established:** Full-season calibrated playoff/title/last-place probabilities, targets/routes and post-injury usage modeling, weather adjustments, international travel penalties, and prospective lineup decision-regret. There were only ten held-out matchups. Do not label an unvalidated simulation a calibrated prediction.
- **Game correlation:** A team-week correlation coefficient can be estimated from historical residuals. Weeks 5–6 Brier did not improve (0.20924 versus 0.20868 independent). **The correlated version stays in shadow mode (rho=0 for primary win estimates)** until a larger *later, untouched* test improves the benchmark. Correlated simulations can be run as diagnostic sensitivity. This avoids promoting extra complexity on the same data used to evaluate it.
- **Lineups:** Every legal QB/2RB/2WR/TE/FLEX/DST/K combination is enumerated. Already-started bench players are excluded. Started roster members remain locked to exact slots. Complete NFL weekly kickoffs (via ESPN public NFL scoreboard) are **required**; invalid or unavailable schedules block lineup output.
- **Volatility:** Heavy-tailed empirical positional residuals sampled from training games, never Gaussian-only. D/ST outcomes are **not clamped at zero**; QB/RB/WR/TE/K may score zero.
- **Game state:** Shared offense factors are modeled and estimated but only promoted upon independent holdout improvement. Document negative outcome sensitivity for quarterback/kicker and defense, and role and overseas-game uncertainty for limited-history players.
- **Input provenance:** Every forecast preserves export timestamp, workflow run, and SHA256 of the raw ESPN snapshot. Artifacts retain pregame predictions for later prospective evaluation.

## Workflow

After the ESPN export succeeds, AAA Forecast Engine runs unit/regression tests, downloads the latest league artifact, executes holdout validation, fetches complete NFL games and kickoff timestamps, reranks all ten league rosters (while respecting locks), and outputs `forecast_output/validation.json`, `forecast_output/forecast.json`, `forecast_output/workload_forecast.json`, and `forecast_output/nfl_kickoffs.json` as a separate Actions artifact. A blocked state also uploads `blocked.json`, never an invented start/sit recommendation.

The scorer uses **league historical points, not ESPN projections**. It is a conservative statistical baseline; unlike the previous subjective model, route/target/injury matchups are **not secretly encoded** as authoritative point adjustments. Risk flags trigger explicit hypothetical sensitivity analyses (not probability-weighted predictions). Current injury-status labels require official-game-day confirmation, and future-week injuries are never mechanically assumed from the current week.

## Local commands

```bash
pip install numpy
PYTHONPATH=analysis python -m unittest discover -s analysis/aaa_engine/tests -v
PYTHONPATH=analysis python -m aaa_engine.cli --snapshot path/to/ESPN_Current_Snapshot_1438350867_2026.json --validate-only --output validation.json
PYTHONPATH=analysis python -m aaa_engine.fetch_kickoffs --year 2026 --week 8 --output kickoffs.json
PYTHONPATH=analysis python -m aaa_engine.cli --snapshot path/to/ESPN_Current_Snapshot_1438350867_2026.json --week 8 --kickoffs kickoffs.json --output week8.json --as-of 2026-10-26T11:05:00Z
```

## Data and methodological cautions

Historical eligibility uses ESPN's retrospective nonzero projected-points field **only as a game/bye filter**, never as the forecast input. This conditions the scored sample; no full unrestricted NFL player population is claimed. Historical final lineup composition is **not** a timestamped pregame decision. The scorer also lacks full historical NFL snap/route/target distributions, and cannot validate travel/OL or weather effects until those inputs exist in a dated archive. Historical validation ends at Week 6, since the Week 7 ESPN export was partial when the backtest was performed. Future completed weeks may be scored separately once a new held-out protocol is frozen.

**Next validation milestone:** Archive at least a full season of genuine pregame predictions, official inactive reports and per-player opportunity inputs, then measure lineup regret and probability calibration against subsequent results. A small Weeks 5–6 holdout should never be promoted as full-season independent validation.

## Optional timestamped context (guarded sensitivity only)

You can supply a sourced context JSON through `--context` for the CLI or `FORECAST_CONTEXT_FILE=/path/to/context.json` in GitHub Actions. Each item is an **unweighted stress test**, not a mean adjustment until historical validation supports it:

```json
{
  "as_of": "2026-10-26T11:00:00Z",
  "sources": ["Official injury report and timestamped team travel report"],
  "player_flags": {"4685278": ["rookie_role_uncertainty"]},
  "external_scenarios": [
    {
      "name": "rookie_role_reverts_to_low_targets",
      "source": "Dated route/target report",
      "player_multipliers": {"4685278": 0.7}
    }
  ]
}
```

The example coefficient is a hypothetical sensitivity choice, **not a causal or empirically calibrated estimate**. Data newer than the forecast `as_of`, missing sources and arbitrary scenario probability weights cause a hard error. `forecast.json` records both ESPN export and NFL kickoff schedule SHA256 hashes.

**Visibility caution:** This repository is publicly visible. The new workflow publishes forecast reports as Actions artifacts, not an additional copy of the raw ESPN export containing member metadata. Do not place sensitive scouting notes or personal information in a public context manifest.
