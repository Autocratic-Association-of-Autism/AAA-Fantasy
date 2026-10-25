# AAA Fantasy forecasting rules v3 (2026-10-25)

## Mandatory prospective decision logic

1. Refresh ESPN league roster, official NFL inactives, game times and opponent starters. Lock actual scores only after games begin or finish, and flag stale data.
2. **When information changes any player's forecast, re-rank every legally eligible lineup combination (including FLEX), not just the mentioned player against a single alternative.** Do this again at every material injury, role or game-context update.
3. Forecast opportunity in layers: team offensive plays; player routes/carries; target/carry share; catch efficiency; yards per opportunity; touchdowns; health/availability. Never equate two high-target games with a secure long-term role.
4. For rookies, short-sample role changes, and veterans returning from injury, allow wider lower-tail outcome distributions. Use the same risk standards across all players.
5. International games trigger travel/acclimation, weather, kickoff-time, team-volume and individual-target-share sensitivity scenarios; **never assign a causal fixed overseas penalty without validated evidence**.
6. Model matchups with paired random draws and uncertainty informed by strictly earlier historical data. Evaluate entire lineups by expected points and conditional win chances; report small differences as uncertain.
7. Apply published future NFL bye weeks to every candidate. Identify missing starters and explicitly label any *assumed* waiver addition instead of silently scoring an unavailable roster position.
8. Evaluate calibration chronologically: MAE, RMSE, interval coverage, win Brier/log loss, and lineup-decision regret. Never fit to observed outcomes and call the forecast prospective.
9. State which portion was backtested. The simple 2026 Weeks 2–4 trained / Weeks 5–6 held-out baseline had MAE ~6.23 PPR on 265 player-weeks, and 7/10 matchup winners; it does NOT validate the injury-and-role-adjusted season simulator or its playoff percentages.
10. Preserve lineups already locked and do not fabricate precision: 100,000 Monte Carlo samples reduce numerical sampling noise, not forecasting uncertainty.

## Case studies prompting v3

* A.J. Brown versus Luther Burden III, 2026 Week 7: underweighted Brown's post-injury efficiency risk and Burden's coverage-driven explosive opportunity.
* Germie Bernard's Paris game, 2026 Week 7: overconfidence in two games of high target volume, and inadequate sensitivity analysis for the overseas game. A disappointing result does not prove travel caused it.
* Before Thursday kickoff, rank Brown, Bernard, Burden and JSN for all WR/FLEX slots together. Do not wait until Sunday to compare Bernard against only Boston.

## Limitations

The October 25 forward projection used a 7:59 AM ET export, fixed Thursday scores and a provisional Paris result. NFL byes are verified, but future injuries, opponent weather, trades, free-agent availability and other managers' changes remain uncertain. Week 10 needs a Loveland bye replacement; Week 11 features JSN, Brown and Boston byes. Future win/title/last-place percentages are scenarios, not fully calibrated probabilities.
