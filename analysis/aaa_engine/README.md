# AAA Fantasy Forecast Engine (v5, 2026)

The league's existing ESPN Fantasy Export workflow supplies raw data. This engine **actually executes** under `.github/workflows/aaa-forecast.yml` after successful ESPN exports and on manual dispatches. No ESPN login details are copied into forecast artifacts; GitHub's `GITHUB_TOKEN` is used to read the existing export artifact.

## Validated and unvalidated parts

- **Independently time-split tested:** Per-player *scoring baseline* from previous completed weeks. Train/select hyperparameters on Weeks 2–4, hold out Weeks 5–6, then deploy the frozen hyperparameters to future weeks. Across 265 held-out player-weeks, MAE=6.2293 PPR points and empirical interval coverage is approximately 77.4% for 80% and 89.1% for 90% intervals.
- **Not established:** Full-season calibrated playoff/title/last-place probabilities, targets/routes and post-injury usage modeling, weather adjustments, international travel penalties, and prospective lineup decision-regret. There were only ten held-out matchups. Do not label an unvalidated simulation a calibrated prediction.
- **Game correlation:** A team-week correlation coefficient can be estimated from historical residuals. Weeks 5–6 Brier did not improve (0.20924 versus 0.20868 independent). **The correlated version stays in shadow mode (rho=0 for primary win estimates)** until a larger *later, untouched* test improves the benchmark. Correlated simulations can be run as diagnostic sensitivity. This avoids promoting extra complexity on the same data used to evaluate it.
- **Lineups:** Every legal QB/2RB/2WR/TE/FLEX/DST/K combination is enumerated. Already-started bench players are excluded. Started roster members remain locked to exact slots. Complete NFL weekly kickoffs (via ESPN public NFL scoreboard) are **required**; invalid or unavailable schedules block lineup output.
- **Volatility:** Heavy-tailed empirical positional residuals sampled from training games, never Gaussian-only. D/ST outcomes are **not clamped at zero**; QB/RB/WR/TE/K may score zero.
- **Game state:** Shared offense factors are modeled and estimated but only promoted upon independent holdout improvement. Document negative outcome sensitivity for quarterback/kicker and defense, and role and overseas-game uncertainty for limited-history players.
- **Input provenance:** Every forecast preserves export timestamp, workflow run, and SHA256 of the raw ESPN snapshot. Artifacts retain pregame predictions for later prospective evaluation.

## Workflow

After the ESPN export succeeds, AAA Forecast Engine runs unit/regression tests, downloads the latest league artifact, executes holdout validation, fetches complete NFL games and kickoff timestamps, reranks all ten league rosters (while respecting locks), and outputs `forecast_output/validation.json`, `forecast_output/forecast.json`, `forecast_output/nfl_kickoffs.json` as a separate Actions artifact. A blocked state also uploads `blocked.json`, never an invented start/sit recommendation.

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
