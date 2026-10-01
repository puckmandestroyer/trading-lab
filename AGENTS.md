# Instructions for future Codex work

- Read `PROJECT_STATE.md` before starting meaningful work.
- Read relevant files in `decisions/` before changing architecture.
- Check Git status before modifying files. If the directory is not a Git repository, report that fact.
- Do not make commits automatically; commit only when explicitly asked.
- Preserve existing notebooks, Python files, and data. Do not modify unrelated files.
- Before large changes, give a short implementation plan.
- Prefer simple, beginner-friendly Python and avoid unnecessary abstractions or classes.
- Do not introduce new frameworks without explaining why they are needed.
- Explain non-obvious code: the owner is learning Python, data analysis, SQL, statistics, and quantitative analysis.
- Never put API keys or secrets directly in source code or notebooks. Use environment variables.
- Never commit `.env`, credentials, generated datasets, or generated experiment results.
- After meaningful changes, update `PROJECT_STATE.md` and `CHANGELOG.md`. Do not log trivial formatting changes.
- Add a new `decisions/*.md` file only for an important architectural decision.
- Keep dependencies minimal and introduce packages only when the current task needs them.
- Verify changes with checks appropriate to their scope. Do not add tests that merely duplicate empty scaffolding.

## Architecture boundaries

- Strategies produce signals such as BUY, SELL, and HOLD. They must not communicate directly with an exchange or submit orders.
- Design strategies so the same logic can eventually run in historical backtests and demo trading.
- Keep risk management independent from strategies. Strategies must not choose unrestricted position sizes or leverage.
- Keep exchange-specific API code under `src/trading_lab/exchange/`.
- Keep execution and order management separate from strategies and exchange adapters.
- Make analytics reusable across strategies, backtests, and bot instances.
- Use `notebooks/` for research and experiments. Move stable reusable code into `src/trading_lab/` when needed.
- Never manually modify raw data. Save cleaned or transformed versions under `data/processed/`.
- Use `results/` for generated outputs, never application source code.
- During the current scaffolding stage, do not implement strategies, backtesting, exchange connections, databases, dashboards, or deployment unless the user requests that next work.
