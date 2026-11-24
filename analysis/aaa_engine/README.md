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

**Waiver-wire application:** Every forecast also scans the latest ESPN free-agent pool for QB, RB, WR, TE, D/ST and K. The separate `waiver_game_environment.json` report includes each candidate's upcoming opponent, observed team passing/rushing environment, sack-rate proxy, recent opportunity and availability warning. Independent nflverse opportunity estimates are included for players with verified skill-position history; unrostered D/ST and kickers receive matchup context but **no fabricated points estimate**. The league's own ESPN projection is used only to exclude players on bye, never as the underlying score forecast. No add/drop transactions are performed. Thus the same analysis used for Mahomes versus Brissett now appears for receivers, running backs, tight ends, defenses and kickers when evaluating future waivers.

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


## v10 experimental: Opportunity Model v2 shadow track (NOT production)

The `opportunity_v2.py` experiment uses the existing nflverse weekly player
data and play-by-play data; it **does not** modify `forecast.json` or the
existing v6/v9 forecasts.

1. **Team opportunity:** calculate prior-game team pass attempts (excluding
   sacks), rushing attempts, red-zone plays, and team TD counts. Blend recent
   offense and opposing defensive allowances with explicit league shrinkage.
   Opponent identity is known scheduling context; all count inputs precede
   the forecast week.
2. **Individual opportunity:** derive each player's pass-target, rush and
   QB-attempt shares from actual team-level opportunities. A sustained
   two-game increase or decrease changes the recent-game weighting; isolated
   volume changes do not automatically become permanent roles. Shares are
   **conditional on participation**: games without a player observation do
   not mechanically reduce target share. Missing games instead trigger an
   explicit health/availability warning, which must be modeled separately.
3. **Expected PPR:** multiply the new volume estimates by the existing
   v6 smoothed catch, yardage, TD and turnover rates. Player-specific
   red-zone opportunity distributions have **not yet been modeled**;
   team-level red-zone information is included for auditing only.

Two separate files are published: `opportunity_v2_forecast.json` contains
player opportunities and shadow lineup rankings, while
`opportunity_v2_backtest.json` measures MAE, position-specific errors and
lineup regret against the existing baseline/v6 methods on identical
retrospective league-roster observations. All features from NFL games use
weeks strictly less than the scored week. The coefficient choices (offense/
defense 65/35; exponential recency .73; league pseudo-games 3; recent
target/carry weighting .45/.72) are **untuned hypotheses**, not empirical
calibration. The entire model must remain experimental until frozen
prospective samples show improvement.

Known gaps include verified current-season route participation, true
pass-block win rates, player-specific red-zone chances, official inactives
and calibrated uncertainty distributions. If source data fails, the v2 report
is marked BLOCKED, leaving previous models unchanged.


## Game-first 1.0 (Week 11 postmortem; experimental only)

The Week 11 diagnostic motivated a new controlled feature group, not a
retroactively optimized holdout. Production v5 and existing reporting schedules
are preserved.

- **week_completion.json**: detects when the ESPN fantasy scoring period lags
  the NFL scoreboard. Requires every scheduled game's explicit final/post
  marker and all fantasy teams' nine starter scores to reconcile with the
  matchup totals. Raw export and standings remain unchanged. Even after this
  gate, scores are provisional until ESPN advances; actual final timestamp
  relative to the export is not independently archived. For extending NFL
  shadow model training, require a paired NFL stats/PBP record for every
  scheduled team and reciprocal opponent mapping. Missing data is reported and
  an older cutoff is labeled.
- **opportunity_v2_forecast.json**: fixes the target-week/cutoff conflation.
  A forecast for W+2 can explicitly use available completed W data; do not
  label it fresh W+1 data. When the completion gate and full NFL feed agree,
  v2 shadow can use the extended cutoff with v6's prior cutoff separately
  identified. No change to the production baseline.
- **game_first_forecast.json** (model_version game-first-1.0-shadow):
  resample both sides of actual historical NFL games jointly. An empirical
  kernel matches lagged offense/opposing defense pass attempts and carries;
  a separate ablation adds historical sack-rate proximity. Game-state
  production (including yards and touchdowns) remains linked to team
  volume, so high passing demand does not guarantee high points.
  The adaptive role ablation uses recent median opportunity share unless
  sustained change is supported by multiple games. Across all fantasy rosters,
  normalize modeled player shares plus an explicit unmodeled-player residual
  to one for targets, carries and QB attempts. 100,000 paired trials use
  finite integer opportunity allocations and conditional team scoring rates;
  this is not a possession simulator or calibrated individual TD/yardage
  distribution. Missing player histories use labeled v6/baseline fallbacks.
  D/ST and kicker scores/fallbacks are fixed in the partial matchup simulation.
  Opponent submitted next-week lineups and IR slots may not be recorded;
  opponent baseline-optimized lineup is explicitly hypothetical. Unweighted
  injury what-ifs are not medical probability estimates.
- **game_first_backtest.json**: paired skill-player MAE/RMSE/bias, by-position
  and by-week report, opportunity-count errors, D/ST and kicker control audit,
  team score and matchup-margin error, deterministic winner accuracy,
  lineup regret and wins relative to actual opponent scores. Compare baseline,
  v6, v2, v9, game_volume, game_robust and game_pressure. All features use only
  prior weeks. Week 11 is a diagnostic, not an independent holdout.
  ESPN projections are unverified historical fields, excluding weeks whose
  matchup projections are all overwritten by actual scores. Historical end
  of week rosters cannot establish pregame lineup availability. Week 1 has
  no within-season data; Weeks 2–4 tune the existing baseline and cannot
  be scored on that same fitted baseline. The per-week performance report
  refreshes with the existing scheduled forecast workflow.
- **prospective_scorecard.json**: when the completion gate allows, score
  immutable pre-kickoff archives against the reconciled newer scores. Label
  provisional scoring-period advancement. No backfilling a prediction.

Remaining blockers: exact league D/ST and kicker scoring component metadata,
verified player-level red-zone and route participation, individual QB/receiver
efficiency, offensive-line personnel and true pressure/coverage data, drive and
score-state model, stadium weather, medical workload probabilities, manager
behavior and calibrated playoff/transaction probabilities. These remain separate
future feature groups. Do not promote game-first point predictions or partial
scenario win fractions without independent prospective results.


### Game-first 1.1 — individual efficiency ablation

`game_individual` keeps the Game Volume historical-game weights and player
opportunity shares fixed, but allocates team receptions, yards, touchdowns
and interceptions using each player's lagged efficiency relative to the team
in the same observed games. Ratios are shrunk toward 1 with provisional
pseudo-opportunity strengths (25–120) and bounded to 0.25–3. The unmodeled
player bucket retains a neutral ratio. Expected counts are constrained by
targets, catches, carries and attempts. Totals reconcile to the sampled
team scoring-component budgets; impossible budgets trigger an explicitly
counted fallback to Game Volume.

This is a mean-only candidate with its own historical paired errors and
lineup comparison. It does not change the Game Pressure trial distribution,
the production baseline, or the scheduled reporting cadence. Do not
interpret its optimized mean-only lineup as a calibrated win-probability
optimum. No automatic promotion. Week 11 remains a development diagnostic.


### Participation risk 1.0 — restricted workload research

`participation_risk_forecast.json` and `participation_risk_backtest.json`
use earlier offensive snap observations, completed-team-game coverage and
weekly player stats. Established roles are classified as normal observed,
one missed team game, two or more missed team games, or a recent snap drop
(at most 60% of the median of earlier observed games). Byes are not missed
games; sparse team snap feeds and ambiguous normalized player names are
excluded. Absence from an observed snap report is not a diagnosis.

The conditional candidate adjusts v6's targets, carries and attempts with
exposure-weighted empirical ratios from earlier same-position/risk-class
cases, excluding the evaluated player's team/name/position key. At least 12
informative cases and six distinct keys are required per metric; ratios
are shrunk toward 1 with 20 prior cases. The retrospective sample conditions
on positive offensive snaps and a matched stat row, so it estimates
workload conditional on participation, not the probability of being active.
No timestamp-unverified historical injury labels enter training.

Current ESPN and nflverse injury reports are informational, with timestamp
limitations disclosed. Half-workload and unavailable sensitivity cases are
unweighted illustrations; they are not medical predictions. Lineup comparison
is suppressed when kickoff locks are present. No roster or primary model
changes, no teammate workload redistribution, no independent holdout, and no
automatic promotion. The scheduled forecast archives both new reports.


### Special teams 1.0 — dedicated D/ST and kicker shadows

Separate fixed-penalty ridge models learn residuals of actual AAA league
fantasy points relative to the lagged scoring baseline. Core D/ST features
are sack and interception opportunity and opposing offensive TD proxies;
core kicker features are FG attempts, offensive TDs and red-zone plays.
Expanded features add pass/rush EPA, pace, and third-down conversion/QB
hits where supported. All features summarize earlier completed games from
both relevant opposing units. Missing capability or insufficient team
history blocks adjustment. Fits use only preceding labeled examples, a
minimum of 24 observations and eight NFL teams, and a fixed penalty of 30.
Weeks 2–4 belong to baseline training, so residual examples begin Week 5.
Report genuine paired and fallback-inclusive retrospective errors and
historical ESPN comparisons separately. Week 11 is diagnostic, not a
holdout. Forecasts include rostered and free-agent D/ST and K, but do not
establish kicker starting-job security or perform transactions.

`Scoring_Rules` is a new additive export section with original ESPN stat
IDs, points, overrides and scoring item JSON. An unavailable or invalid
settings response leaves the section empty and marks the League status;
no default scoring rules are substituted. Existing exports remain usable.
The first dedicated special-teams model learns the league's awarded
fantasy points directly; it does not reconstruct stat-based scoring.
Missing fumble-lost, return-TD, kick distance, actual drive and verified
weather features remain limitations. No calibrated scoring distribution
or model promotion. Existing three-hour schedules and production baseline
are preserved.


### Player distributions 1.0 — mean-preserving marginal uncertainty

The `distribution_forecast.json` and `distribution_backtest.json` reports
compare three residual laws with identical lagged baseline means: position
pool, 32 nearest projected-production observations (including boundary
ties), and a personalized blend. At least three own prior observations are
required; own-history weight is n/(n+8). Each law is centered at the
same mean, with negative scoring outcomes retained rather than clipped.
This isolates marginal uncertainty rather than changing point predictions.
Historical tests from Week 5 use only prior observations (baseline
hyperparameters fixed in Weeks 2–4). Report exact CRPS, 80/90% interval
coverage and width, 90th-percentile pinball loss, upper-tail exceedance
and fixed position-specific breakout-threshold Brier scores. Historical
matchups use reconciled final starters and 10,000 common-random-number
trials; current fixed baseline lineups use 100,000 trials. No same-game
covariance, injury probability or calibrated win claim. Suppress live
matchup simulations after any kickoff. These are experimental reports
only; no scoring, schedule or production changes.


### Matchup win 1.0 — signed dependence and lineup objective shadow

The positional empirical law is the uncertainty control. Signed lagged
standardized residual products are grouped by same NFL team or opposing NFL
teams and position pair, with at least 12 pairs and shrinkage of 80 prior
pairs; latent correlations are capped at ±0.45 and repaired to a
positive-definite correlation matrix. A Gaussian copula preserves each
marginal law; it does not enforce the game-first finite opportunity budget.
Compare independent and correlated fixed-lineup Brier scores. Enumerate
unique legal pregame player sets, fail closed beyond 3,000, and compare
mean-maximizing, independent win, correlated win and robust (top three
opposing mean lineups, equally weighted) objectives. The opponent scenarios
are hypothetical, not inferred manager probabilities. Selection uses 4,000
historical / 20,000 live draws; evaluation uses distinct seeds and 6,000 /
100,000 draws respectively. Historical final rosters are retrospective;
Week 11 is diagnostic only. Report realized lineup regret and wins against
actual opponent scores, not counterfactual opponent decisions. Block live
simulations after kickoff. No production promotion or schedule change.
