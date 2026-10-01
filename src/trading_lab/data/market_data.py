"""Download, normalize, validate, and save historical OHLCV snapshots."""

from pathlib import Path
import time
import warnings

import numpy as np
import pandas as pd
import requests

from trading_lab.exchange.bybit_market_data import fetch_kline_page


OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]
NUMERIC_COLUMNS = OHLCV_COLUMNS[1:]
MINUTE_INTERVALS = {"1", "3", "5", "15", "30", "60", "120", "240", "360", "720"}


def _interval_duration(interval):
    """This first loader supports Bybit's fixed minute-based intervals."""
    if str(interval) not in MINUTE_INTERVALS:
        raise ValueError(f"Unsupported interval {interval!r}; use a Bybit minute interval.")
    return pd.Timedelta(minutes=int(interval))


def _utc_timestamp(value):
    """Interpret timezone-free inputs as UTC; convert aware inputs to UTC."""
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        raise ValueError("Date boundaries cannot be missing.")
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def invalid_ohlc_mask(df):
    """Identify inconsistent candles without removing any rows."""
    return (
        (df["high"] < df[["open", "close", "low"]].max(axis=1))
        | (df["low"] > df[["open", "close", "high"]].min(axis=1))
        | (df[["open", "high", "low", "close"]] <= 0).any(axis=1)
        | (df["volume"] < 0)
    )


def validate_ohlcv(df, *, interval="60", start=None, end=None):
    """Check data strictly and return a summary; never discard invalid candles.

    Optional start/end boundaries describe [start, end): the first candle is
    included, and the candle opening at end is excluded. Passing them also
    checks coverage at both ends, not just gaps inside the dataset.
    """
    if list(df.columns) != OHLCV_COLUMNS:
        raise ValueError(f"Expected exactly {OHLCV_COLUMNS}; got {list(df.columns)}.")
    if df.empty:
        raise ValueError("The OHLCV dataset is empty.")
    if not isinstance(df["timestamp"].dtype, pd.DatetimeTZDtype):
        raise ValueError("timestamp must be a timezone-aware pandas datetime column.")
    if str(df["timestamp"].dt.tz) != "UTC":
        raise ValueError("timestamp must use UTC.")
    for column in NUMERIC_COLUMNS:
        if not pd.api.types.is_numeric_dtype(df[column]) or pd.api.types.is_bool_dtype(df[column]):
            raise ValueError(f"{column} must contain numeric values.")

    problems = []
    missing = df.isna().sum()
    duplicates = int(df["timestamp"].duplicated().sum())
    chronological = bool(df["timestamp"].is_monotonic_increasing)
    if missing.sum():
        problems.append(f"Missing values: {missing.to_dict()}")
    if duplicates:
        problems.append(f"Duplicate timestamps: {duplicates}")
    if not chronological:
        problems.append("Timestamps are not in chronological order.")
    nonfinite = ~np.isfinite(df[NUMERIC_COLUMNS].to_numpy(dtype=float)).all(axis=1)
    invalid = invalid_ohlc_mask(df)
    if nonfinite.any():
        problems.append(f"Non-finite numeric rows: {int(nonfinite.sum())}\n{df.loc[nonfinite].head().to_string(index=False)}")
    if invalid.any():
        problems.append(f"Invalid OHLC/volume rows: {int(invalid.sum())}\n{df.loc[invalid].head().to_string(index=False)}")

    duration = _interval_duration(interval)
    timestamps = df["timestamp"].dropna()
    missing_candles = pd.DatetimeIndex([], tz="UTC")
    if not timestamps.empty:
        first = _utc_timestamp(start) if start is not None else timestamps.min()
        stop = _utc_timestamp(end) if end is not None else timestamps.max() + duration
        if first >= stop or first.floor(duration) != first or stop.floor(duration) != stop:
            raise ValueError("Coverage boundaries must be ordered and aligned to the candle interval.")
        expected = pd.date_range(first, stop, freq=duration, inclusive="left")
        actual = pd.DatetimeIndex(timestamps)
        missing_candles = expected.difference(actual)
        unexpected = actual.difference(expected)
        if len(missing_candles):
            problems.append(f"Missing candles: {len(missing_candles)}; first examples: {list(missing_candles[:5])}")
        if len(unexpected):
            problems.append(f"Out-of-range or misaligned timestamps: {list(unexpected[:5])}")
    if problems:
        raise ValueError("OHLCV validation failed:\n" + "\n".join(problems))
    return {
        "rows": len(df),
        "earliest_timestamp": df["timestamp"].min(),
        "latest_timestamp": df["timestamp"].max(),
        "missing_values": missing.to_dict(),
        "duplicate_timestamps": duplicates,
        "chronological": chronological,
        "invalid_ohlc_rows": int(invalid.sum()),
        "missing_candles": len(missing_candles),
    }


def normalize_klines(rows):
    """Convert Bybit arrays into six UTC/numeric columns, oldest first.

    Identical duplicate candles are removed with a warning. Conflicting
    duplicates raise an error because choosing a value would hide a problem.
    Bybit's seventh field, turnover, is outside this dataset's core schema.
    """
    if not rows:
        raise ValueError("Bybit returned no candles for the requested period.")
    for row in rows:
        if not isinstance(row, list) or len(row) != 7:
            raise ValueError(f"Expected a seven-field Bybit candle, got {row!r}.")
        if not isinstance(row[0], str) or not row[0].isdigit():
            raise ValueError(f"Invalid millisecond timestamp: {row[0]!r}.")
    df = pd.DataFrame([row[:6] for row in rows], columns=OHLCV_COLUMNS)
    try:
        df["timestamp"] = pd.to_datetime(pd.to_numeric(df["timestamp"], errors="raise"), unit="ms", utc=True)
        for column in NUMERIC_COLUMNS:
            df[column] = pd.to_numeric(df[column], errors="raise").astype("float64")
    except (ValueError, TypeError, OverflowError) as error:
        raise ValueError(f"Cannot normalize Bybit candle values: {error}") from error

    repeated = df[df["timestamp"].duplicated(keep=False)]
    if not repeated.empty:
        conflicts = repeated.groupby("timestamp")[NUMERIC_COLUMNS].nunique(dropna=False).gt(1).any(axis=1)
        if conflicts.any():
            bad_rows = repeated[repeated["timestamp"].isin(conflicts[conflicts].index)]
            raise ValueError(f"Conflicting duplicate candles:\n{bad_rows.head().to_string(index=False)}")
        duplicate_count = int(df["timestamp"].duplicated().sum())
        warnings.warn(f"Removed {duplicate_count} identical duplicate candle(s).", UserWarning, stacklevel=2)
        df = df.drop_duplicates("timestamp")
    else:
        duplicate_count = 0
    df = df.sort_values("timestamp").reset_index(drop=True)
    df.attrs["duplicate_rows_removed"] = duplicate_count
    return df


def download_ohlcv(*, start, end, symbol="BTCUSDT", category="spot", interval="60", page_limit=1000):
    """Download completed candles in [start, end), then validate full coverage.

    Bybit returns newest candles first. Each next request ends one millisecond
    before the oldest candle in the previous page, so pagination moves backward.
    No partial dataset is saved if requests or validation fail.
    """
    duration = _interval_duration(interval)
    start_time, end_time = _utc_timestamp(start), _utc_timestamp(end)
    if start_time >= end_time:
        raise ValueError("start must be earlier than end.")
    if start_time.floor(duration) != start_time or end_time.floor(duration) != end_time:
        raise ValueError("start and end must align to the candle interval.")
    if end_time > pd.Timestamp.now(tz="UTC").floor(duration):
        raise ValueError("end must exclude the currently open candle and future candles.")
    if not isinstance(page_limit, int) or isinstance(page_limit, bool) or not 1 <= page_limit <= 1000:
        raise ValueError("page_limit must be an integer between 1 and 1000.")
    if category not in {"spot", "linear", "inverse"}:
        raise ValueError("category must be spot, linear, or inverse.")
    if not isinstance(symbol, str) or not symbol or not symbol.isalnum() or symbol != symbol.upper():
        raise ValueError("symbol must be an uppercase alphanumeric symbol, such as BTCUSDT.")

    start_ms = start_time.value // 1_000_000
    cursor = end_time.value // 1_000_000 - 1
    rows = []
    pages = 0
    with requests.Session() as session:
        while cursor >= start_ms:
            page = fetch_kline_page(
                session, category=category, symbol=symbol, interval=str(interval),
                start_ms=start_ms, end_ms=cursor, limit=page_limit,
            )
            if not page:
                break  # Full-range validation below detects incomplete coverage.
            page_times = [int(row[0]) for row in page]
            if min(page_times) < start_ms or max(page_times) > cursor:
                raise RuntimeError("Bybit returned candles outside the requested page boundaries.")
            rows.extend(page)
            pages += 1
            cursor = min(page_times) - 1
            if cursor >= start_ms:
                time.sleep(0.1)  # Keep the small historical download comfortably paced.

    df = normalize_klines(rows)
    validate_ohlcv(df, interval=interval, start=start_time, end=end_time)
    df.attrs.update({"pages_downloaded": pages, "symbol": symbol, "category": category, "interval": str(interval)})
    return df


def save_ohlcv(df, path, *, interval="60"):
    """Validate and create a snapshot; refuse to overwrite an existing raw file."""
    validate_ohlcv(df, interval=interval)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation preserves previously collected raw snapshots.
    with path.open("x", encoding="utf-8", newline="") as output:
        df.to_csv(output, index=False)
    return path


def load_ohlcv_csv(path, *, interval="60", start=None, end=None):
    """Restore UTC timestamps and numeric dtypes, then validate the local file."""
    df = pd.read_csv(path, dtype={column: "float64" for column in NUMERIC_COLUMNS})
    if list(df.columns) != OHLCV_COLUMNS:
        raise ValueError(f"Expected exactly {OHLCV_COLUMNS}; got {list(df.columns)}.")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="raise")
    validate_ohlcv(df, interval=interval, start=start, end=end)
    return df
