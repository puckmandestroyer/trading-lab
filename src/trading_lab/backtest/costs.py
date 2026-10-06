"""Self-financing long-trade accounting with adverse slippage and notional fees."""

from math import isfinite
from numbers import Real

import pandas as pd

from trading_lab.backtest.performance import calculate_trade_results
from trading_lab.risk.position_sizing import calculate_position_budget


def _rate(value, name: str) -> float:
    """Rates are decimal fractions in [0, 1); never parse strings or bools."""
    if not isinstance(value, Real) or isinstance(value, bool):
        raise ValueError(f"{name} must be numeric, finite, >= 0 and < 1; bool is not allowed.")
    try:
        rate = float(value)
    except OverflowError as error:
        raise ValueError(f"{name} must be finite, >= 0 and < 1.") from error
    if not isfinite(rate) or not 0 <= rate < 1:
        raise ValueError(f"{name} must be finite, >= 0 and < 1.")
    return rate


def calculate_trade_results_with_costs(
    trades: pd.DataFrame,
    initial_capital: float = 10_000.0,
    fee_rate: float = 0.0,
    slippage_rate: float = 0.0,
    position_fraction=1.0,
) -> pd.DataFrame:
    """Return separate cost-aware results without modifying the ledger/baseline.

    Input is the Stage 4.5 six-column ledger. Reuse the unchanged gross helper
    for ledger/capital validation and typed context; its computed amounts are
    NOT used for net sizing or compounding. Its numerical validation also applies.
    Preserve raw prices, times, IDs, status, and index; omit optional columns.

    One long spot trade at a time allocates position_fraction of current NET
    capital; default 1.0 preserves all-in behavior. The risk helper supplies
    a budget INCLUDING the entry fee; reserve stays outside the position.
    Effective entry = recorded entry * (1 + slippage_rate), effective exit =
    recorded exit * (1 - slippage_rate). Quantity = position_budget /
    (effective entry * (1 + fee_rate)), so entry_notional + entry_fee = budget.
    Fees apply to effective quote notionals. Reserve is derived from total
    capital_before minus that full entry spend, not stored in a new column.

    CLOSED gross_pnl uses recorded prices and THIS cost-sized quantity;
    price_adjusted_pnl uses effective prices. Net PnL subtracts both fees;
    net_trade_return = net_pnl / capital_before, and net_capital_after =
    capital_before + net_pnl, independently compounded into the next trade.
    Both capital fields mean TOTAL portfolio capital, including reserve.
    Thus gross_pnl with costs is not a separate zero-cost baseline simulation.

    OPEN trades record capital_before, effective_entry_price, quantity,
    entry_notional, and entry_fee only. Exit, full-round-trip total_fees, and
    realized fields stay NaN. Entry fee is known, but no open-position valuation
    or realized net result is fabricated. The existing schema/order is unchanged;
    all accounting columns remain float64.
    No leverage, quantity rounding, execution changes, files, or APIs are added.
    """
    fee = _rate(fee_rate, "fee_rate")
    slippage = _rate(slippage_rate, "slippage_rate")
    baseline = calculate_trade_results(trades, initial_capital)
    required = ["trade_id", "entry_time", "entry_price", "exit_time", "exit_price", "status"]
    result = baseline[required].copy()
    columns = [
        "capital_before", "effective_entry_price", "effective_exit_price", "quantity",
        "entry_notional", "exit_notional", "entry_fee", "exit_fee", "total_fees",
        "gross_pnl", "price_adjusted_pnl", "net_pnl", "net_trade_return", "net_capital_after",
    ]
    accounting = []
    capital = float(initial_capital)  # Already validated by the baseline helper.
    if result.empty:
        # Public sizing parameters must be valid even without an executed entry.
        calculate_position_budget(capital, position_fraction)
    for row in result.itertuples(index=False):
        capital_before = capital
        position_budget = calculate_position_budget(capital_before, position_fraction)
        effective_entry = float(row.entry_price) * (1 + slippage)
        entry_cost_per_unit = effective_entry * (1 + fee)
        if (
            not isfinite(capital_before) or capital_before <= 0
            or not isfinite(entry_cost_per_unit) or entry_cost_per_unit <= 0
        ):
            raise ValueError("Calculated entry cost and capital must be finite and positive.")
        quantity = position_budget / entry_cost_per_unit
        entry_notional = quantity * effective_entry
        entry_fee = entry_notional * fee
        if not isfinite(quantity) or quantity <= 0 or not isfinite(entry_notional) or entry_notional <= 0:
            raise ValueError("Calculated quantity/notional must be finite and positive, without underflow.")
        if row.status == "OPEN":
            accounting.append([
                capital_before, effective_entry, float("nan"), quantity,
                entry_notional, float("nan"), entry_fee, float("nan"), float("nan"),
                float("nan"), float("nan"), float("nan"), float("nan"), float("nan"),
            ])
            continue

        effective_exit = float(row.exit_price) * (1 - slippage)
        if not isfinite(effective_exit) or effective_exit <= 0:
            raise ValueError("Calculated effective exit price must be finite and positive.")
        exit_notional = quantity * effective_exit
        exit_fee = exit_notional * fee
        total_fees = entry_fee + exit_fee
        gross_pnl = quantity * (float(row.exit_price) - float(row.entry_price))
        price_adjusted_pnl = quantity * (effective_exit - effective_entry)
        net_pnl = price_adjusted_pnl - total_fees
        net_return = net_pnl / capital_before
        capital_after = capital_before + net_pnl
        amounts = [
            exit_notional, exit_fee, total_fees, gross_pnl, price_adjusted_pnl,
            net_pnl, net_return, capital_after,
        ]
        if not all(isfinite(value) for value in amounts) or capital_after < 0:
            raise ValueError("Calculated cost results must be finite and net capital non-negative.")
        accounting.append([
            capital_before, effective_entry, effective_exit, quantity,
            entry_notional, exit_notional, entry_fee, exit_fee, total_fees,
            gross_pnl, price_adjusted_pnl, net_pnl, net_return, capital_after,
        ])
        capital = capital_after

    for number, column in enumerate(columns):
        result[column] = pd.Series([row[number] for row in accounting], index=result.index, dtype="float64")
    return result
