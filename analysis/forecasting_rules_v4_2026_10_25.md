# AAA Fantasy forecasting rules v4 — Week 7 corrective controls

**Status:** These are mandatory prospective analysis requirements, not evidence that the model is automatically deployed or fully calibrated. Existing ESPN Fantasy Export does not run a validated fantasy prediction engine.

1. **Freeze decisions before kickoff:** Record timestamp, full team roster, position-eligible candidates, official inactives, weather/travel news, current ESPN lineup, forecasts and ranking *before* first applicable kickoff. Never claim an outcome-informed revision was a prospective forecast.
2. **Full lineup re-ranking every relevant lock window:** Re-evaluate all legal combinations (QB, 2 RB, 2 WR, TE, RB/WR/TE FLEX, DST, K) before Thursday, early international games, Sunday, SNF and MNF. Preserve already-locked starters and exclude already-locked bench players. Don't restrict a user-flagged question to a comparison of two names when other viable starters exist.
3. **Predict opportunity, not names:** Team plays/pass attempts/runs -> snaps/routes -> individual target/carry shares -> catches/yards and touchdowns. Apply historically supported regression for recently promoted rookies and returning injured players, and explicitly model a low-target scenario.
4. **Game-specific disruption:** QB return, OL/pass rush and coverage, run-defense weakness, possible blowout and international travel must trigger scenario sensitivity tests. Do not apply unvalidated arbitrary overseas penalties.
5. **Joint-game uncertainty:** Don't independently simulate all players when their outcomes share team/game state. Model shared bad offensive games affecting QB and K and blowouts affecting a team's RB usage and DST. Validate correlations from older games rather than fit Week 7 outcomes.
6. **Real DST negative tails and QB zero-touchdown tails:** Include -3 or worse D/ST outcomes and very low QB scoring possibilities; quantify the likelihood of these outcomes for each candidate.
7. **Report close calls as close calls:** If rankings flip under plausible usage changes or the expected advantage is much smaller than historical forecast error, report ranges and decision sensitivity. The manager's Bears-player preference may break objective ties, not override meaningful fantasy advantages.
8. **Prospective evaluation:** Compare timestamped pregame forecasts with actuals and with ESPN/rolling baselines using MAE, RMSE, interval coverage, Brier/log loss and realizable start/sit regret. Report separately the accuracy of manually adjusted player means and matchup win predictions.
9. **Don't equate Monte Carlo size with calibration.** The prior 265-player-week 2026 holdout tested a simple historical baseline, not the override-heavy simulator. Display any playoff percentages as provisional until the full model is tested.
10. **Require operational checks:** Fail when the roster or kickoff data is incomplete, when a recently started bench player is proposed, or when risk-sensitive candidates have no alternative scenarios.

## Week 7 evidence
- ESPN export 2026-10-26T03:18:56Z: user **100.10**, Chance **104.90**.
- Missed Thursday alternatives: Burden **23.7** vs Bernard **5.7** or Brown **7.8**; start Burden in either slot would have won.
- Sunday alternative: Skattebo **19.1** vs Hubbard **10.0**; switching would have won.
- Correct call: Braelon Allen **19.4** vs benched Dobbins **8.3**.
- Major forecast errors: Mahomes **6.0** vs **17.0** estimated, Panthers D/ST **-3.0** vs **5.7** estimated, Butker **3.0** vs **8.1** estimated.
- The previous simulator sampled individual player outcomes independently and hard-coded many role-specific means; prior numerical win odds are not certified. The previous 54% playoff estimate is stale after the Week 7 loss.

**Engineering not yet completed:** GitHub Actions integration, model-wide correlation calibration, archive of timestamped prospective predictions, full-season holdout and fresh season re-simulation following the loss.
