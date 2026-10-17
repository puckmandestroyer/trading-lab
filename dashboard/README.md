# Generic runtime dashboard

Stage 12.1d implements a local, read-only operational dashboard. It consumes existing validated `health.json` and `events-YYYY-MM-DD.jsonl` files. It never opens RuntimeStore/SQLite, accesses a broker or Telegram, or writes observability/trading/configuration files.

The v1 execution runtime remains one `ema_trend` BTCUSDT hourly (`60`) bot. That identity is displayed as data. The dashboard template is strategy-agnostic and keyed by broker/account/bot/strategy/symbol/timeframe. A compatible future `bot2 / donchian / ETHUSDT / 60` observability instance uses the same loader, DashboardModel, formatting and six-view template without a strategy-specific branch. No Donchian execution strategy or multi-bot runtime is implemented.

## Performance first

Select strategy/model in the main header → inspect current Net P&L / Return / Risk Equity / Drawdown / Daily P&L / Position on the left → inspect historical **Strategy Performance %** on the right → inspect trades/risk/health/events. The Overview then shows secondary operational status and at most five latest confirmed closed cycles. Native Streamlit containers, columns, metrics, tabs and charts provide the layout without CSS/JavaScript injection. Project-local [`.streamlit/config.toml`](../.streamlit/config.toml) defaults to light mode with white/light-gray surfaces, dark text and a restrained blue accent; global user configuration is untouched.

Performance % is bot risk equity relative to authorized risk capital:

```text
Net P&L = risk_equity - risk_capital_quote
Return % = (risk_equity - risk_capital_quote) / risk_capital_quote * 100
```

This is not wallet/whole-account, realized-only trade or deposit-adjusted account performance. `DashboardPerformance` and `performance_series(model)` calculate with Decimal only, independently of the caller's precision. Net subtraction and finite decimal ratios retain source precision; recurring ratios use Decimal context rounding. Inactive/missing exact risk evidence is **Unavailable**, never zero. Positive amounts/returns carry `+`, negatives retain `-`, and genuine zero is `0` / `0%`. Currency comes from validated `quote_currency`. Cards round percentages to six decimal places; expandable exact current values and historical Decimal percentages remain available. Drawdown is displayed as a loss percentage; its original numerator/denominator remain in Risk. Position preserves pending/uncertain/HALT states.

The main chart uses only retained `RISK_BLOCKED` / `RISK_TRIPPED` events containing exact risk equity and valuation time with `risk_configuration_digest` matching current health. Missing/incompatible bases are excluded and explicitly mark performance history incomplete. A same-configuration child rearm does not reset history. No new event type or observability producer is added. The separate technical equity/daily-PnL charts still expose original retained amounts, not normalized performance.

The dashboard never invents historical performance observations. If fewer than two compatible retained risk-equity observations exist, current Return is still shown but the graph reports **Insufficient performance history.** No snapshot becomes historical evidence, no fake zero-to-current line or hourly grid is created, and no missing hours are interpolated. The chart's labeled zero reference uses existing observation timestamps only; float conversion remains confined to the guarded final `chart_rows` boundary.

The header presents stored `60` as `1H` without changing supported execution timeframes. The Runtime Health identity table retains canonical broker/account/bot/strategy/symbol/timeframe, including raw `60`. Refresh remains secondary and read-only.

## Start locally

From the project root, with the project virtual environment installed:

```bash
PYTHONPATH=src ../.venv/bin/streamlit run dashboard/app.py \
  --server.address 127.0.0.1 \
  --server.headless true \
  --browser.gatherUsageStats false \
  -- --observability-root /absolute/private/path/to/observability
```

This command binds the UI to localhost and disables usage telemetry. Keep those flags for local-only operation. No credentials or API keys are needed. The root is explicit: the application does not guess folders, create a Demo instance or start a trading runtime.

The root and hashed instance directories must already exist with private permissions (0700), and files must be private (0600), as produced by frozen observability storage. Discovery reads only direct hashed child candidates and validates their health snapshots; friendly labels show the parsed strategy/symbol/timeframe/bot/account identity. One valid candidate loads naturally; multiple candidates use the same read-only selector. Empty roots show “No valid Trading Lab observability instance found.” Invalid candidates are reported as unavailable.

Only manual refresh is provided. Clicking **Refresh local files**, selecting an instance or changing a filter reruns local reads. There are no BUY/SELL/cancel/rearm/force-flat/configuration/Live controls, background pollers or automatic event-emission hooks.

## Six views

- **Overview:** performance summary and compatible retained Performance % history first; secondary runtime/display health, risk/market/reconciliation status, five-cycle preview, then owned quantity, mark, ENTRY count/limit, candle/pending facts and snapshot age.
- **Position / Orders:** exact current exposure/evidence, desired position, pending identity/kind/phase/deadline, broker/reconciliation times, retained action/execution events and available quantity observations. ACK is not fill evidence.
- **Risk:** exact fixed configuration, equity/peak/daily baseline/PnL, drawdown numerator/denominator, ENTRY count, trip origin and epoch/configuration identity. Retained trip/rearm history remains separate; wallet totals are not risk equity.
- **Trades:** only retained confirmed OPEN → quantity transitions → CLOSE cycles with coherent exposure. Initial/pre-close quantities, original times, execution references and exact supplied realized PnL are shown. Referenced execution rows preserve price/quantity/signed fee/currency. Cycle times are the confirmed OPEN/CLOSE event occurrence times; retained executions show their separate execution timestamps. No synthetic PnL, inferred fee totals, currency conversion or order-size estimate.
- **Runtime Health:** generated/process/scheduler/cycle times, raw state/reason/checkpoint, health/reasons, stored evidence freshness, candle/market/reconciliation/broker facts, pending deadline, HALT/rearm and observability status. Viewer-time snapshot freshness is shown separately.
- **Event / Error History:** recent validated events, all four severities visible by default, severity/type filters, deterministic newest-first order and expandable full event references. Validated observability JSON is displayed, never raw broker payloads.

Financial text retains canonical exact Decimal values. Unknown is **Unavailable**, not zero. Display percentages use Decimal arithmetic rounded to six decimal places; exact numerator/denominator remain available. Charts convert to approximate float only at the final rendering boundary and refuse nonzero-to-zero underflow/non-finite conversion. Quantity, risk-equity and daily-PnL charts use actual retained event observations only. Fewer than two points shows **Insufficient history**; a current snapshot never becomes a fabricated history series.

Stored health can age after writing. The default viewer threshold is **120,000ms**, for display only; future timestamps are UNKNOWN. An old snapshot cannot remain presented as current merely because its stored generated freshness is FRESH. Stored raw health/reasons remain visible; display attention never changes runtime state or deadlines.

## Read-only bounds and integrity

Framework-independent code lives in `src/trading_lab/dashboard/{model,loader,analytics,formatting}.py`; `app.py` renders it through Streamlit. Frozen `health_from_json` / `event_from_json` validate every record. No frozen observability, trading, risk, exchange, strategy or backtest code is changed.

Resource bounds are explicit:

- Discovery: at most 256 root entries / 64 direct candidate instances.
- History: at most 4,096 instance entries, newest 7 UTC segments, 4 MiB per segment / 8 MiB total and 10,000 scanned complete records.
- Display: latest 250 unique events by default; public loader hard maximum 1,000. Ordering is observed time / occurred time / event ID, newest first. Latest observation wins duplicate stable IDs; canonical bytes break exact time ties, independently of file order.
- Health: frozen `MAX_HEALTH_BYTES` (32 KiB). Symlinks (including ancestors), special files, hard links, broader permissions, path escape, malformed health and identity mismatch are refused. Reads use no-follow directory-relative descriptors; no permissions are repaired or loosened.

A torn final JSONL line preserves valid preceding events with a degraded warning. An invalid complete record, identity/segment mismatch, unsafe file or exceeded resource bound makes selected event history explicitly unavailable; current valid health can still be shown. Older unselected segments are not claimed to have been checked. Files are never repaired, overwritten or deleted.

History is a bounded display, not a durable trade journal. Current LONG with no retained OPEN remains a known position with incomplete/unavailable trade history. Missing transitions, execution/fee evidence or exact PnL stay explicit. Catch-up cannot recreate overwritten historical transitions. Notification receipts are never read. Snapshot and event boundaries are not claimed to be simultaneous.

## Validation and future work

Stage 12.1d baseline is independently owner-reviewed / FROZEN at `fcae94557e536181f3db9e577817dada1c33665f` (81 dashboard / 3,239 total tests). The narrow performance/light-theme correction is COMPLETE / owner review pending. Local validation: **34 new correction tests**, **115 dashboard tests** (22 model / 38 analytics / 31 unchanged loader / 24 app), **142 frozen observability tests**, **73 Telegram tests** and **3,273 full-suite tests**, failures/errors/skips **0/0/0**. Targeted Stage 11/runtime/EMA checks, `pip check` and both Git diff checks passed; golden remains 54 decisions / 2 placements / 2 fills / 0 cancellations / 1 risk epoch, exact IDs/economics unchanged. Unit tests use synthetic local parser fixtures; Streamlit AppTest renders without a browser/server and guards network access. Frozen production, loader, schema, Decisions, requirements (`streamlit==1.66.0`), data and notebooks remain unchanged. No real runtime monitoring, credential, broker, Telegram or user-DB operation occurred. Stages 12.1a–c remain FROZEN; Stage 12.1 remains INCOMPLETE, Stage 12.1e NOT STARTED, v1.0.0 NOT RELEASED. Automatic runtime observability emission remains a separately reviewed integration boundary. Do not begin 12.1e automatically.

A future separate POST-v1 Research / Backtest Dashboard may add strategy, symbol/coin and timeframe selection, backtests, cross-asset comparisons, strategy comparison, robustness, walk-forward and parameter heatmaps. It may share presentation helpers but remains a separate application boundary. None of those research features or multi-strategy execution is implemented here.
