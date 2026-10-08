# 012 — Strategy Robustness Contract

- Date: 2026-10-08
- Status: Accepted
- Scope: Stage 8.1 documentation/architecture only; no robustness package, production API, tests, or notebook is created.
- Completed baseline: `41dcb320fa32ea239b70632c81d05e130f1d8ec0` — `Complete Stage 7 position sizing`.
- Related decisions: [010 — Generic strategy / backtest contract](010_generic_strategy_backtest_contract.md) and [011 — Risk and position sizing](011_risk_and_position_sizing.md), which remain authoritative.

## Context / problem

Stages 5–7 established correctness of the analytics, generic backtest, and fixed-allocation machinery. Stage 8 asks whether observed strategy behavior remains reasonably consistent across later periods, nearby parameters, and multiple chronological windows, or is fragile and sample-specific. Correct machinery alone does not establish a robust strategy.

## Goal and non-goals

Evaluate robustness through time splits, out-of-sample evaluation, parameter sensitivity/stability, and walk-forward diagnostics. Stage 8 does not attempt to discover the most profitable EMA parameters, maximize Sharpe or final equity, find one "best" pair, or optimize against the full historical sample. A narrow isolated favorable optimum is evidence of fragility, not success. Robustness is not a single magic score.

## Terminology

| Term | Meaning |
| --- | --- |
| In-sample (IS) | Earlier data used for research or descriptive parameter evaluation before a later period. |
| Out-of-sample (OOS) | Strictly later evaluation data not used to tune conclusions or choices for that same test period. The seen-data limitation below still applies. |
| Parameter sensitivity | Evaluation of a predefined finite parameter grid to understand variation around the baseline. |
| Parameter stability | Broadly similar behavior across nearby valid choices rather than one isolated favorable point. |
| Walk-forward evaluation | Repeated chronological evaluation across multiple later windows. |
| Robustness | Stability of strategy behavior across time and parameter perturbations, assessed through multiple diagnostics. |

## Chronological split and boundary rules

Use chronological order only: earlier IS precedes later OOS. Never use random train/test splits, shuffle candles, or mix future observations into an earlier evaluation. Use explicit half-open intervals `[start, end)` to avoid ambiguous overlap; preserve the existing timestamp, row-alignment, and hourly-candle contracts.

Determine boundaries from timestamps, fixed durations, fixed chronological proportions, or explicit dates before inspecting favorable returns. A chronological 70%/30% split, calendar dates, expanding windows, and rolling windows are possible research designs, not defaults selected here. Exact split defaults and API/file design belong to later milestones.

## No-look-ahead rules

At timestamp T, signals and indicators may depend only on information available at or before the accepted strategy-information boundary. Decision 010 remains authoritative: candle N completes, its decision becomes available, and a valid event may fill at the immediately following candle N+1 OPEN. Stage 8 must not redefine execution timing or use later prices to improve a fill.

Future information must not influence signals, indicator values, parameter conclusions for the same OOS window, execution, position sizing, metrics attributed to an earlier window, or window-specific decisions. Post-run metrics use only the corresponding segment's canonical outputs and cannot feed back into that segment's choices.

## Cold-start / warm-up semantics

Every independently evaluated IS, OOS, or walk-forward segment is self-contained. It starts FLAT with its own initial capital and fresh strategy, execution, accounting, and ledger state. No pre-window candles or indicator state initialize it; no pre-window `desired_position`, `executed_position`, open trade, capital path, or ledger state may silently carry in.

Run the existing strategy's normal initialization inside the segment. For baseline EMA20/50, retain `warmup_candles=50`: the first 50 candles are initialization-only HOLD/FLAT, eligibility begins with candle 51, and eligibility alone never creates an entry. The existing first-close EMA seed and eligible crossover/state rules apply. Never fabricate a boundary entry merely because fast EMA is above slow EMA.

Warm-up candles remain part of the segment's chronological observation window. Capital stays uninvested during initialization, with no synthetic trade. Metrics retain the canonical cash periods and equity observations; do not manually remove warm-up periods because their results look unfavorable.

A final signal without a next OPEN inside the segment remains unfilled. Do not borrow another segment's first OPEN or force a terminal exit. An executed position may finish OPEN: realized exit fields remain missing, and canonical equity may mark the holding plus reserve without a sale or hypothetical exit costs.

Cold starts are simpler, leakage-resistant, and compatible with current APIs, but may omit exposure a continuously running system would carry across a boundary. Continuous-state walk-forward is outside initial Stage 8 and requires a future explicitly reviewed contract.

## Existing engine reuse and responsibilities

Compose the existing production layers:

```text
supplied candles → strategy generation → run_backtest_pipeline(...)
                 → independent GROSS/NET accounting
                 → reserve-aware equity → existing analytics
```

Do not create a second backtest engine or duplicate execution, trade pairing, position sizing, fees/slippage, PnL, equity, drawdown, or Sharpe/Sortino formulas. Strategy owns intent/indicator warm-up, risk owns budgets, accounting owns quantity/PnL, equity owns reserve-aware valuation, and the pipeline owns orchestration only. Analytics remains sizing-policy-free. Existing APIs, schemas, validation, and no-terminal-liquidation semantics remain unchanged.

## Baseline strategy status

The existing reusable strategy is EMA trend with `fast_span=20`, `slow_span=50`, and `warmup_candles=50`. This is the baseline research configuration, not an optimal, best, validated, or profitable configuration. Stage 8 evaluates its robustness without changing production defaults.

## Position-sizing relationship

Decision 011 remains authoritative: support a run-level fixed scalar `position_fraction` in `0 < f <= 1`, default 1.0, applied to each path's current capital. Risk supplies the capital budget; accounting determines quantity and compounds total capital; equity retains reserve cash. No leverage, shorts, or dynamic sizing is added.

Normally hold `position_fraction` fixed within an experiment while varying time or strategy parameters. Do not jointly search strategy parameters and allocation fractions as an optimization grid. Sizing robustness may be studied separately if needed.

## Cost-model relationship

GROSS and NET remain independent existing accounting paths; evaluate both when useful. Canonical NET research assumptions may remain `fee_rate=0.001` and `slippage_rate=0.0005`. These are frozen research assumptions, not claims about current exchange fees. Do not query exchange pricing. Keep costs and sizing assumptions consistent within a comparison.

## OOS evaluation rules

Treat OOS as strictly later, unseen evaluation data for the choices under study. Metrics may be calculated after the run, but the result must not retroactively change the same window's parameters, strategy rules, signals, execution assumptions, or financial formulas. If the researcher revises a strategy after seeing OOS results, that period is no longer untouched for the revised strategy; disclose that limitation.

## Parameter sensitivity rules

Stage 8.3 will evaluate a deterministic, predefined finite grid with explicit values and valid strategy combinations only. EMA spans must be positive integers with `fast_span < slow_span`; existing strategy validation, including positive-integer warm-up, remains authoritative. Record the warm-up policy and hold it consistent within the comparison. Use the same supplied data, window rules, costs, and sizing assumptions for every combination. The exact default grid belongs to Stage 8.3 and is not frozen here.

Tables may describe equity, returns, trade counts, drawdown, Sharpe, and Sortino for valid pairs. Rankings are descriptive research only. Do not automatically replace EMA20/50, declare the maximum-Sharpe pair "best," write optimized values into defaults, deploy the highest-equity pair, or keep searching until OOS looks favorable. Sensitivity is not optimization.

## Parameter stability principle

Distinguish a broad stable region, where nearby choices behave similarly, from a sharp isolated peak whose neighbors are materially worse. Treat an isolated peak as a robustness warning. Preserve underlying diagnostics; Stage 8.1 defines no universal stability threshold or composite `robustness_score`.

## Walk-forward rules

Stage 8.5 evaluates fixed, predefined configurations across multiple successive chronological windows, including EMA20/50. Automatic optimization or parameter reselection is not required for Stage 8 completion. Each independently evaluated segment follows the same cold-start policy.

Permit expanding history (earlier training history grows) and rolling history (a fixed-length earlier training window moves forward) in principle. The initial deterministic mode and exact window defaults must be documented when implemented; no training window may include future candles relative to its test period.

If a later implementation studies train-based selection, define its deterministic rule before viewing the corresponding test window, use training data only, apply the rule unchanged to the later test window, and label it research-only. No adaptive selection is implemented in Stage 8.1 or required by this contract.

Keep independent OOS results separate: each has its own initial capital and state. Do not silently concatenate disjoint windows into a continuous equity path with invented capital continuity. Aggregate statistics must be labeled as aggregation of independent evaluations. A continuous stitched portfolio requires a separate explicit contract.

## Metrics / diagnostics and benchmark

Reuse existing analytics where applicable: trade count, final equity, total return, realized/portfolio drawdown, Sharpe, Sortino, win/loss metrics, and time exposure. Not every metric is required in every table. Preserve existing formulas, return timing, annualization, risk-free/MAR handling, and output meanings; record comparable assumptions rather than inventing financial calculations.

Interpret multiple diagnostics together. Highest return, highest Sharpe, lowest drawdown, or the most profitable windows alone does not prove robustness. No composite score is introduced.

Handle zero-trade, low-trade, no-losing-return, and no-downside windows according to existing analytics contracts. Preserve documented NaN/undefined results and zero-denominator infinities honestly; do not fabricate finite Sharpe, Sortino, or profit factor values or invent trades to fill a table.

Buy-and-Hold remains an independent comparison path. A window may construct its benchmark on that same window using the existing benchmark contract; changing EMA parameters does not change benchmark construction. Do not optimize benchmark parameters.

## Determinism

The same supplied candles, window definition, strategy parameters/warm-up, initial capital, `position_fraction`, cost assumptions, and analytics settings must produce the same results. No randomness is needed; do not introduce random seeds to mask nondeterminism. Preserve inputs and existing validation rather than silently repairing them.

## Data policy and limitations

Initial examples/regression may use the existing frozen local BTCUSDT 1-hour snapshot. Never silently download replacement data. Later reusable robustness logic should accept supplied candle DataFrames and remain dataset-agnostic where practical, rather than being hardwired to BTC files.

This BTC sample has already been inspected extensively in Stages 1–7. Its chronological OOS procedures are methodological robustness checks within an already-seen research sample, not proof from pristine never-seen data. A genuinely untouched future dataset would provide stronger evidence. Results remain sample-specific historical research.

## Out-of-scope features

Stage 8 adds no live/demo orders, exchange runtime/adapter, polling, WebSocket, API keys, database, or bot runtime. It does not introduce Optuna, hyperopt, Bayesian/genetic optimization, ML/deep learning, feature-selection frameworks, automatic strategy discovery/deployment, dynamic live parameter switching, portfolio optimization, or multi-asset/multi-bot allocation. Monte Carlo and bootstrap engines require separate approval. Keep the research understandable and inspectable.

## Accepted Stage 8 roadmap

| Milestone | Status after Stage 8.1 |
| --- | --- |
| 8.1 — Robustness Contract | Complete; Decision 012 Accepted, documentation/architecture only. |
| 8.2 — Time Split / OOS Evaluation Core | Awaits explicit owner approval; not started. |
| 8.3 — Parameter Sensitivity Engine | Planned; not started. |
| 8.4 — Parameter Stability Analysis | Planned; not started. |
| 8.5 — Walk-Forward Evaluation | Planned; not started. |
| 8.6 — Robustness Summary / Diagnostics | Planned; not started. |
| 8.7 — Strategy Robustness Notebook | Planned; not started. |
| 8.8 — Final Stage 8 Audit + Docs | Planned; not started. |

## Consequences / trade-offs

Chronological cold starts and explicit assumptions make comparisons deterministic and inspectable, at the cost of missing continuous boundary exposure. Independent windows cannot be presented as one compounded live portfolio. Nearby-parameter and multi-window diagnostics can reveal fragility, but do not establish universal validity or erase prior data exposure.

Stage 8.1 creates only this decision and updates project documentation. Later code may live under a focused package such as `src/trading_lab/robustness/`; no package, placeholder, or public API is created now. Exact API/file design belongs to Stage 8.2, which requires explicit approval and has not started.
