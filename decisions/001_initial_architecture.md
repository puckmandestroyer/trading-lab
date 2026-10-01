# 001 — Initial architecture

- Date: 2026-10-01
- Status: Accepted
- Scope: Project structure and intended boundaries; no trading functionality implemented.

## Context

Trading Lab will grow from historical cryptocurrency data research into a strategy research and demo-trading platform. It should eventually support multiple independent strategies and bot instances without duplicating strategy logic or binding the application to one exchange.

## Decisions

### Separate signals, risk, execution, and exchanges

Strategies will receive market data and produce signals such as BUY, SELL, or HOLD. A strategy must not call an exchange or submit orders.

```text
Market Data
    ↓
Strategy
    ↓
Signal
    ↓
Risk Manager
    ↓
Execution Engine
    ↓
Exchange
```

Risk management is independent from individual strategies. Strategies must not independently determine unrestricted position sizes or leverage. Future centralized risk controls must account for multiple bot instances; execution and order management will handle approved trading actions.

### Reuse strategies in backtests and demo trading

```text
                 Strategy
                     |
              generate signal
                     |
          +----------+----------+
          |                     |
      Backtest              Demo Trading
       Engine                Execution
```

The same strategy logic should run in both contexts. Historical simulation and demo execution will supply their respective data and execution behavior while respecting independent risk controls. Signal types and interfaces will be designed when actual strategy work requires them.

### Contain exchange-specific behavior

All exchange-specific API details belong under `src/trading_lab/exchange/`. Future adapters may include `bybit.py` or `binance.py`; those files are not created now. The rest of the application should use exchange-independent concepts rather than directly depending on one exchange API.

### Share analytics

`src/trading_lab/analytics/` will provide analysis reusable across strategies and bot instances. Future metrics may include total return, benchmark return, win rate, average win, average loss, profit factor, expectancy, volatility, Sharpe ratio, Sortino ratio, maximum drawdown, number of trades, and fees. None are implemented now.

### Separate research from application code

Use `notebooks/` for exploration, research, visualization, and experiments. Move stable reusable code into `src/trading_lab/` when needed. Keep beginner-friendly implementations and avoid speculative classes, interfaces, and frameworks.

### Preserve original data and separate generated outputs

`data/raw/` holds original market data. Never manually modify it. Store cleaned or transformed copies in `data/processed/` and record dataset provenance. `results/` holds generated experiment or backtest output, never application source code. Ignore datasets and generated results in Git while preserving directory placeholders.

### Defer infrastructure until needed

PostgreSQL, dashboards for each bot and strategy, a global comparison dashboard, and Docker deployment are long-term goals. Their functionality and dependencies are deferred. Only the first-stage research packages are listed now; no exchange library, web framework, database client, or machine learning dependency is introduced.

## Consequences

The scaffold makes future responsibilities visible without implementing them. Existing Python placeholders and the misspelled `data/proceseed/` directory are preserved. New reusable code belongs under `src/trading_lab/`; new transformed datasets belong under `data/processed/`. Future important architecture changes require a new decision record.
