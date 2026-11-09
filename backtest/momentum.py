"""Momentum breakout swing strategy and its test (see Momentum_Strategy.md).

Usage (from the trading folder):
    .venv\\Scripts\\python -m backtest.momentum fetch
    .venv\\Scripts\\python -m backtest.momentum test --set dev
    .venv\\Scripts\\python -m backtest.momentum test --set holdout     # run once, after dev is read
    .venv\\Scripts\\python -m backtest.momentum intraday --set dev
    .venv\\Scripts\\python -m backtest.momentum scan                   # today's setups, after fetch
"""
import argparse
import io
import urllib.request
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path("data/s1500")
OUT_DIR = Path("results/momentum")
SP_PAGES = ["List_of_S%26P_500_companies", "List_of_S%26P_400_companies", "List_of_S%26P_600_companies"]
MARKET = ("SPY", "QQQ")
SPLIT_SEED = 20261106

# Costs
COMMISSION = 0.01      # $/share each side
SLIPPAGE = 0.001       # fraction of price, on entry, stops and next-open exits

# Scan
MIN_PRICE = 3.0
MIN_VOLUME = 500_000
MIN_ADR = 0.02
RS_LOOKBACK = 63
RS_TOP = 0.20

# Base
BASE_MIN, BASE_MAX = 5, 25
POLE_LOOKBACK = 40
POLE_MIN_GAIN, POLE_ADR_MULT = 0.15, 5.0
BASE_RANGE_ADR = 3.5
TAIL_RANGE_ADR = 0.8
TOUCH_ADR = 0.25
MAX_PRIOR_BREAKOUTS = 1

# Entry and exit
BREAKOUT_RVOL = 1.5
MAX_STOP_ATR = 1.5
TARGET_R = 3.0
CONTROLS = 20

# Portfolio
MAX_POSITIONS = 5
RISK_PER_TRADE = 0.01
MAX_POSITION = 0.20


# ---------------------------------------------------------------- data

def fetch_universe():
    tickers = []
    for page in SP_PAGES:
        req = urllib.request.Request(f"https://en.wikipedia.org/wiki/{page}", headers={"User-Agent": "Mozilla/5.0"})
        html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8")
        table = next(t for t in pd.read_html(io.StringIO(html)) if "Symbol" in t.columns or "Ticker symbol" in t.columns)
        col = "Symbol" if "Symbol" in table.columns else "Ticker symbol"
        tickers += table[col].astype(str).str.replace(".", "-", regex=False).tolist()
    return sorted(set(tickers))


def first_unfinished_day():
    """Bars from this date on aren't final: today's bar only counts once the session is over."""
    now = pd.Timestamp.now(tz="America/New_York")
    return now.normalize().tz_localize(None) + pd.Timedelta(days=int(now.hour * 60 + now.minute >= 16 * 60 + 15))


def fetch(chunk=100):
    import yfinance as yf

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tickers = fetch_universe()
    pd.DataFrame({"ticker": tickers}).to_csv(DATA_DIR / "universe.csv", index=False)
    print(f"universe: {len(tickers)} tickers")
    today = first_unfinished_day()
    todo = list(MARKET) + tickers
    saved = 0
    for start in range(0, len(todo), chunk):
        batch = todo[start:start + chunk]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            raw = yf.download(batch, period="10y", interval="1d", auto_adjust=False, group_by="ticker",
                              progress=False, threads=True)
        for t in batch:
            if t not in raw.columns.get_level_values(0):
                continue
            df = raw[t].copy()
            df.columns = [c.lower() for c in df.columns]
            df = df[["open", "high", "low", "close", "volume"]].dropna()
            df = df[df.index < today]  # drop today's partial bar
            if len(df) >= 300:
                df.to_csv(DATA_DIR / f"{t}_1d.csv")
                saved += 1
        print(f"{min(start + chunk, len(todo))}/{len(todo)} done, {saved} saved")


def split_universe():
    tickers = sorted(p.name[:-len("_1d.csv")] for p in DATA_DIR.glob("*_1d.csv"))
    listed = set(pd.read_csv(DATA_DIR / "universe.csv")["ticker"])
    tickers = [t for t in tickers if t in listed and t not in MARKET]
    shuffled = np.random.default_rng(SPLIT_SEED).permutation(tickers)
    half = len(shuffled) // 2
    return sorted(shuffled[:half]), sorted(shuffled[half:])


def load_bars():
    """All daily bars on the SPY calendar, as a dict of DataFrames per field (dates × tickers)."""
    frames = {}
    for p in sorted(DATA_DIR.glob("*_1d.csv")):
        df = pd.read_csv(p, index_col=0, parse_dates=True)
        frames[p.name[:-len("_1d.csv")]] = df[~df.index.duplicated()]
    calendar = frames["SPY"].index
    return {f: pd.DataFrame({t: df[f].reindex(calendar) for t, df in frames.items()})
            for f in ("open", "high", "low", "close", "volume")}


def ema(s, span):
    return s.ewm(span=span, adjust=False, min_periods=span).mean()


def market_green(bars):
    green = pd.Series(True, index=bars["close"].index)
    for t in MARKET:
        c = bars["close"][t]
        for span in (8, 21, 50):
            green &= c > ema(c, span)
    return green


def rs_rank(bars):
    ret = bars["close"].drop(columns=list(MARKET)) / bars["close"].drop(columns=list(MARKET)).shift(RS_LOOKBACK) - 1
    return ret.rank(axis=1, pct=True)


def rs_top(bars):
    return rs_rank(bars) >= 1 - RS_TOP


# ---------------------------------------------------------------- one ticker

class Series:
    """Numpy arrays and indicators for one ticker."""

    def __init__(self, ticker, bars, green, rs):
        self.ticker = ticker
        self.dates = bars["close"].index
        self.o, self.h, self.l, self.c, self.v = (bars[f][ticker].to_numpy(float)
                                                  for f in ("open", "high", "low", "close", "volume"))
        close = bars["close"][ticker]
        self.e8, self.e21, self.e50 = (ema(close.dropna(), s).reindex(self.dates).to_numpy() for s in (8, 21, 50))
        daily_range = pd.Series(self.h / self.l - 1, index=self.dates)
        self.adr20 = daily_range.rolling(20).mean().to_numpy()
        self.adr50 = daily_range.rolling(50).mean().to_numpy()
        prev = close.shift(1)
        tr = pd.concat([bars["high"][ticker] - bars["low"][ticker], (bars["high"][ticker] - prev).abs(),
                        (bars["low"][ticker] - prev).abs()], axis=1).max(axis=1, skipna=False)
        self.atr = tr.rolling(14).mean().to_numpy()
        self.vol20 = pd.Series(self.v, index=self.dates).rolling(20).mean().shift(1).to_numpy()
        self.green = green.to_numpy()
        self.rs = rs[ticker].to_numpy()


def find_base(s, i):
    """Longest base ending the day before i that passes the rules, as (N, high, low), or None."""
    if i < BASE_MAX + POLE_LOOKBACK + 5 or not np.isfinite(s.adr50[i - 1] + s.e50[i - 1]):
        return None
    if np.isnan(s.l[i - BASE_MAX - POLE_LOOKBACK]):  # listed too recently for the pole lookback
        return None
    if s.c[i - 1] <= s.e21[i - 1]:
        return None
    for n in range(BASE_MAX, BASE_MIN - 1, -1):
        checks, hi, lo = base_checks(s, i, n)
        if all(checks.values()):
            return n, hi, lo
    return None


def base_checks(s, i, n):
    """Each base rule for the n days before i, as ({rule: passed}, base high, base low)."""
    a = i - n
    adr_px = s.adr50[i - 1] * s.c[i - 1]
    hi, lo = np.max(s.h[a:i]), np.min(s.l[a:i])
    pole_gain = np.max(s.h[a - 5:a]) / np.min(s.l[a - POLE_LOOKBACK:a]) - 1
    touches = np.flatnonzero(s.h[a:i] >= hi - TOUCH_ADR * adr_px)
    return dict(
        pole=not pole_gain < max(POLE_MIN_GAIN, POLE_ADR_MULT * s.adr50[i - 1]),
        range=bool(hi - lo <= BASE_RANGE_ADR * adr_px),
        tail=not np.mean(s.h[i - 5:i] - s.l[i - 5:i]) > TAIL_RANGE_ADR * adr_px,
        volume=not np.mean(s.v[a:i]) >= np.mean(s.v[a - 20:a]),
        above_e50=not lo < s.e50[i - 1],
        above_e21=not s.c[i - 1] <= s.e21[i - 1],
        touches=len(touches) >= 2 and touches[-1] - touches[0] >= 2,
    ), hi, lo


def passes_scan(s, i):
    return (s.green[i] and s.rs[i] and s.c[i] > MIN_PRICE and s.v[i] > MIN_VOLUME and s.c[i] > s.c[i - 1]
            and s.adr20[i] >= MIN_ADR and s.c[i] > s.e8[i] and s.c[i] > s.e21[i] and s.c[i] > s.e50[i])


def manage(s, start, entry, stop, on_entry_day=None):
    """Sell in quarters from bar `start` on. Returns the legs [(bar, fraction, price)] and the exit reason."""
    risk = entry - stop
    target = entry + TARGET_R * risk
    left, t1, did8, did21, pending = 1.0, False, False, False, 0.0
    legs = []
    for k in range(start, len(s.o)):
        if np.isnan(s.c[k]):
            continue
        if pending > 0:
            sold = min(pending, left)
            legs.append((k, sold, s.o[k] * (1 - SLIPPAGE)))
            left -= sold
            pending = 0.0
            if left <= 1e-9:
                return legs, "ema50"
        if s.o[k] <= stop:
            legs.append((k, left, s.o[k] * (1 - SLIPPAGE)))
            return legs, "breakeven" if t1 else "stop"
        if s.l[k] <= stop:
            legs.append((k, left, stop * (1 - SLIPPAGE)))
            return legs, "breakeven" if t1 else "stop"
        if not t1 and s.h[k] >= target:
            legs.append((k, 0.25, max(target, s.o[k])))
            left -= 0.25
            t1 = True
            stop = max(stop, entry)
        if s.c[k] < s.e50[k]:
            pending = left
        elif t1:
            if s.c[k] < s.e21[k] and not did21:
                pending = 0.25 * (not did8) + 0.25
                did8 = did21 = True
            elif s.c[k] < s.e8[k] and not did8:
                pending = 0.25
                did8 = True
    last = np.flatnonzero(np.isfinite(s.c))[-1]  # the ticker's own last bar: the calendar can run a day ahead of it
    legs.append((last, left, s.c[last]))
    return legs, "open"


def r_multiple(legs, entry, risk):
    pnl = sum(f * (px - entry) for _, f, px in legs) - 2 * COMMISSION
    return pnl / (risk + 2 * COMMISSION)


def _mark_prior_breakouts(s):
    """How many raw breakouts happened since the last close below EMA50, for each day."""
    out = np.zeros(len(s.c), dtype=int)
    count = 0
    for i in range(1, len(s.c)):
        if not np.isfinite(s.c[i] + s.e50[i]) or s.c[i] < s.e50[i]:
            count = 0
            continue
        out[i] = count
        if is_raw_breakout(s, i):
            count += 1
    return out


def is_raw_breakout(s, i):
    if s.v[i] >= BREAKOUT_RVOL * s.vol20[i] and s.c[i] > np.nanmax(s.h[max(0, i - BASE_MIN):i], initial=-np.inf):
        base = find_base(s, i)
        return bool(base and s.c[i] > base[1])
    return False


def signals_for(s, use_green=True):
    """Signal-day candidates in date order, with the one-open-trade-per-ticker rule applied."""
    rows = []
    prior = _mark_prior_breakouts(s)
    busy_until = -1
    for i in range(1, len(s.c) - 1):
        if i <= busy_until or not np.isfinite(s.c[i] + s.atr[i] + s.e50[i]):
            continue
        if not s.c[i] > s.c[i - 1] or not s.rs[i] or not (s.green[i] or not use_green):
            continue
        if s.l[i] >= np.nanmin(s.l[i - BASE_MIN:i]) and s.c[i] <= np.nanmax(s.h[i - BASE_MIN:i]):
            continue  # neither a new high nor an undercut of even the shortest base
        base = find_base(s, i)
        if base is None:
            continue
        hi, lo = base[1], base[2]
        kind = None
        if (s.c[i] > hi and s.v[i] >= BREAKOUT_RVOL * s.vol20[i] and s.c[i] > s.e8[i]
                and s.c[i] > s.e21[i] and s.c[i] > s.e50[i] and prior[i] <= MAX_PRIOR_BREAKOUTS):
            kind = "breakout"
        elif s.l[i] < lo < s.c[i] <= hi and s.c[i] > s.e21[i] and s.c[i] > s.e50[i]:
            kind = "undercut"
        if kind is None or s.c[i] <= MIN_PRICE or s.v[i] <= MIN_VOLUME or s.adr20[i] < MIN_ADR:
            continue
        entry = s.c[i] * (1 + SLIPPAGE)
        stop = s.l[i]
        if entry - stop > MAX_STOP_ATR * s.atr[i] or entry <= stop:
            continue
        legs, reason = manage(s, i + 1, entry, stop)
        busy_until = legs[-1][0]
        rows.append(dict(ticker=s.ticker, i=i, date=s.dates[i], kind=kind, base_days=base[0], entry=entry, stop=stop,
                         risk_pct=(entry - stop) / entry, stop_atr=(entry - stop) / s.atr[i], volume=s.v[i],
                         r=r_multiple(legs, entry, entry - stop), reason=reason, exit_date=s.dates[legs[-1][0]],
                         days_held=legs[-1][0] - i, legs=legs))
    return rows


def control_r(s, rows, rng):
    """Random entries on days that pass the market filter and scan, with the same stop multiple and exits."""
    if not rows:
        return
    pool =np.array([i for i in range(1, len(s.c) - 1)
                     if np.isfinite(s.c[i] + s.atr[i] + s.e50[i]) and passes_scan(s, i)])
    for row in rows:
        vals = []
        if len(pool):
            for i in rng.choice(pool, CONTROLS):
                entry = s.c[i] * (1 + SLIPPAGE)
                stop = entry - row["stop_atr"] * s.atr[i]
                if stop > 0:
                    legs, _ = manage(s, i + 1, entry, stop)
                    vals.append(r_multiple(legs, entry, entry - stop))
        row["control_r"] = np.mean(vals) if vals else np.nan


# ---------------------------------------------------------------- portfolio

def run_portfolio(trades, bars):
    """Daily equity curve taking trades by date, then highest volume, up to MAX_POSITIONS."""
    dates = bars["close"].index
    start = dates.searchsorted(dates[0] + pd.Timedelta(days=365))
    by_day = {}
    for t in sorted(trades, key=lambda x: (x["i"], -x["volume"])):
        by_day.setdefault(t["i"], []).append(t)
    close = {t: bars["close"][t].ffill().to_numpy() for t in {x["ticker"] for x in trades}}
    equity = np.ones(len(dates))
    cash, open_pos, taken = 1.0, [], 0
    exposure = np.zeros(len(dates))
    for d in range(start, len(dates)):
        for pos in list(open_pos):
            for k, frac, px in pos["legs"]:
                if k == d:
                    cash += pos["shares"] * frac * px - COMMISSION * pos["shares"] * frac
                    pos["left"] -= frac
            if pos["left"] <= 1e-9:
                open_pos.remove(pos)
        value = lambda: cash + sum(p["shares"] * p["left"] * close[p["ticker"]][d] for p in open_pos)
        for t in by_day.get(d, []):
            if len(open_pos) >= MAX_POSITIONS:
                break
            eq = value()
            shares = min(RISK_PER_TRADE * eq / (t["entry"] - t["stop"]), MAX_POSITION * eq / t["entry"])
            cost = shares * t["entry"]
            if cost > cash:
                continue
            cash -= cost + COMMISSION * shares
            open_pos.append(dict(ticker=t["ticker"], shares=shares, left=1.0, legs=t["legs"]))
            taken += 1
        equity[d] = value()
        exposure[d] = 1 - cash / equity[d]
    curve = pd.Series(equity[start:], index=dates[start:])
    return curve, taken, exposure[start:].mean()


def curve_stats(curve):
    years = (curve.index[-1] - curve.index[0]).days / 365.25
    ret = curve.pct_change().dropna()
    return dict(cagr=(curve.iloc[-1] / curve.iloc[0]) ** (1 / years) - 1, max_dd=(1 - curve / curve.cummax()).max(),
                sharpe=ret.mean() / ret.std() * np.sqrt(252))


def month_ci(r, dates, rng, boots=5000):
    """Bootstrap CI of the mean, resampling calendar months because trades cluster in time."""
    df = pd.DataFrame({"r": r, "m": pd.DatetimeIndex(dates).to_period("M")}).dropna()
    g = df.groupby("m").r.agg(["sum", "count"]).to_numpy()
    idx = rng.integers(0, len(g), (boots, len(g)))
    means = g[idx, 0].sum(axis=1) / g[idx, 1].sum(axis=1)
    return df.r.mean(), np.percentile(means, 2.5), np.percentile(means, 97.5)


# ---------------------------------------------------------------- reports

def _line(label, r, dates, rng):
    r = np.asarray(r, float)
    if len(r) == 0:
        return f"| {label} | 0 | | | |"
    if len(set(pd.DatetimeIndex(dates).to_period("M"))) < 3:
        return f"| {label} | {len(r)} | {(r > 0).mean():.0%} | {r.mean():+.3f} | too few months |"
    m, lo, hi = month_ci(r, dates, rng)
    return f"| {label} | {len(r)} | {(r > 0).mean():.0%} | **{m:+.3f}** | {lo:+.2f} … {hi:+.2f} |"


def run_set(name, tickers, bars, green, rs, rng, use_green=True, with_control=True):
    rows = []
    for t in tickers:
        s = Series(t, bars, green, rs)
        tr = signals_for(s, use_green)
        if with_control:
            control_r(s, tr, rng)
        rows += tr
    print(f"{name}: {len(rows)} trades")
    return rows


def test(which):
    dev, holdout = split_universe()
    tickers = dev if which == "dev" else holdout
    bars = load_bars()
    green, rs = market_green(bars), rs_top(bars)
    rng = np.random.default_rng(42)

    rows = run_set("primary", tickers, bars, green, rs, rng)
    df = pd.DataFrame(rows).dropna(subset=["control_r"])
    no_filter = pd.DataFrame(run_set("no market filter", tickers, bars, green, rs, rng, use_green=False, with_control=False))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.drop(columns="legs").to_csv(OUT_DIR / f"trades_{which}.csv", index=False)

    m, lo, hi = month_ci(df.r, df.date, rng)
    dm, dlo, dhi = month_ci(df.r - df.control_r, df.date, rng)
    passed = lo > 0 and dlo > 0

    curve, taken, exposure = run_portfolio(rows, bars)
    st = curve_stats(curve)
    spy = _spy_total_return(curve.index)
    ew = bars["close"][tickers].loc[curve.index].pct_change(fill_method=None).mean(axis=1).fillna(0).add(1).cumprod()
    sp, es = curve_stats(spy), curve_stats(ew)

    hdr = "| Slice | Trades | Win % | Expectancy (net R) | 95% CI (by month) |\n|---|---|---|---|---|"
    lines = [f"# Momentum strategy test — {which} set", "",
             f"{len(tickers)} tickers, {df.date.min():%Y-%m-%d} → {df.date.max():%Y-%m-%d}. Rules: Momentum_Strategy.md. "
             "Current index members only, so absolute returns are flattered by survivorship.", "",
             "## Signals vs random entries", "", hdr,
             _line("Signals", df.r, df.date, rng),
             _line("Random entries on scan days (avg of 20 per signal)", df.control_r, df.date, rng),
             _line("Breakouts", df.r[df.kind == "breakout"], df.date[df.kind == "breakout"], rng),
             _line("Undercuts", df.r[df.kind == "undercut"], df.date[df.kind == "undercut"], rng),
             _line("Signals with market filter off", no_filter.r, no_filter.date, rng), "",
             f"**Signal minus random:** {dm:+.3f}R per trade (95% CI {dlo:+.2f} … {dhi:+.2f}).", "",
             f"**Success criteria met: {'YES' if passed else 'NO'}** (signal CI above 0 and signal-minus-random CI above 0).", "",
             "## Trade shape", "",
             f"Median risk {df.risk_pct.median():.1%} of price ({df.stop_atr.median():.2f} ATR). Median hold {df.days_held.median():.0f} days, "
             f"mean {df.days_held.mean():.0f}. Best {df.r.max():+.1f}R, worst {df.r.min():+.1f}R. "
             f"Top 5% of trades make {df.r.nlargest(max(1, len(df) // 20)).sum() / df.r.sum():.0%} of total R."
             if df.r.sum() > 0 else
             f"Median risk {df.risk_pct.median():.1%} of price ({df.stop_atr.median():.2f} ATR). Median hold {df.days_held.median():.0f} days. "
             f"Best {df.r.max():+.1f}R, worst {df.r.min():+.1f}R.", "",
             "| Exit | Trades | Avg R |", "|---|---|---|"]
    for reason, g in df.groupby("reason"):
        lines.append(f"| {reason} | {len(g)} | {g.r.mean():+.2f} |")
    lines += ["", "## Portfolio (5 positions, 1% risk, 20% max position)", "",
              "| | CAGR | Max drawdown | Sharpe |", "|---|---|---|---|",
              f"| Strategy ({taken} trades, avg {exposure:.0%} invested) | {st['cagr']:+.1%} | {st['max_dd']:.1%} | {st['sharpe']:.2f} |",
              f"| SPY with dividends | {sp['cagr']:+.1%} | {sp['max_dd']:.1%} | {sp['sharpe']:.2f} |",
              f"| Equal-weight this ticker set, no dividends | {es['cagr']:+.1%} | {es['max_dd']:.1%} | {es['sharpe']:.2f} |", "",
              "## By year", "", "| Year | Trades | Expectancy | Random |", "|---|---|---|---|"]
    for y, g in df.groupby(df.date.dt.year):
        lines.append(f"| {y} | {len(g)} | {g.r.mean():+.3f} | {g.control_r.mean():+.3f} |")
    (OUT_DIR / f"report_{which}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def _spy_total_return(index):
    import yfinance as yf

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = yf.download("SPY", period="10y", interval="1d", auto_adjust=True, progress=False, multi_level_index=False)
    c = df["Close"]
    c.index = pd.DatetimeIndex(c.index).tz_localize(None).normalize()
    return c.reindex(index).ffill().bfill()


# ---------------------------------------------------------------- intraday version

def load_hourly(ticker):
    import yfinance as yf

    path = DATA_DIR / "1h" / f"{ticker}_1h.csv"
    if path.exists():
        df = pd.read_csv(path, index_col=0)
        df.index = pd.to_datetime(df.index, utc=True).tz_convert("America/New_York")
        return df
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = yf.download(ticker, period="730d", interval="1h", auto_adjust=False, prepost=False,
                         progress=False, multi_level_index=False)
    if df is None or df.empty:
        return None
    df.columns = [c.lower() for c in df.columns]
    df = df[["open", "high", "low", "close", "volume"]].dropna()
    df.index = pd.to_datetime(df.index, utc=True).tz_convert("America/New_York")
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path)
    return df


def intraday_ticker(s, hourly, prior):
    """First hourly close above the trigger on volume pace, with the stop at the low of the day so far."""
    rows = []
    by_day = {d: g for d, g in hourly.groupby(hourly.index.tz_localize(None).normalize())}
    # Normal pace: mean cumulative volume at each hour of the session over the prior 20 days.
    cum = pd.DataFrame({d: g.volume.cumsum().reset_index(drop=True) for d, g in by_day.items()}).T.sort_index()
    pace = cum.rolling(20, min_periods=10).mean().shift(1)
    first = s.dates.searchsorted(min(by_day))
    busy_until = -1
    for i in range(max(first, 1), len(s.c) - 1):
        if i <= busy_until or s.dates[i] not in by_day:
            continue
        p = i - 1
        if not (s.green[p] and s.rs[p] and s.c[p] > MIN_PRICE and s.v[p] > MIN_VOLUME and s.adr20[p] >= MIN_ADR
                and s.c[p] > s.e8[p] and s.c[p] > s.e21[p] and s.c[p] > s.e50[p] and prior[i] <= MAX_PRIOR_BREAKOUTS):
            continue
        if s.h[i] <= np.nanmax(s.h[i - BASE_MIN:i]):
            continue
        base = find_base(s, i)
        if base is None or s.h[i] <= base[1]:
            continue
        bars = by_day[s.dates[i]]
        normal = pace.loc[s.dates[i]].to_numpy()
        cum_vol, low_so_far, fired = 0.0, np.inf, None
        for n, (_, b) in enumerate(bars.iterrows()):
            cum_vol += b.volume
            low_so_far = min(low_so_far, b.low)
            if b.close > base[1] and n < len(normal) and cum_vol >= BREAKOUT_RVOL * normal[n]:
                fired = n
                entry = b.close * (1 + SLIPPAGE)
                stop = low_so_far
                break
        if fired is None or entry <= stop or entry - stop > MAX_STOP_ATR * s.atr[p]:
            continue
        rest = bars.iloc[fired + 1:]
        if len(rest) and rest.low.min() <= stop:
            legs, reason = [(i, 1.0, stop * (1 - SLIPPAGE))], "stop"
        else:
            legs, reason = manage(s, i + 1, entry, stop)
        busy_until = legs[-1][0]
        rows.append(dict(ticker=s.ticker, date=s.dates[i], entry=entry, stop=stop, risk_pct=(entry - stop) / entry,
                         r=r_multiple(legs, entry, entry - stop), reason=reason, days_held=legs[-1][0] - i,
                         ret=sum(f * (px - entry) for _, f, px in legs) / entry,
                         closed_above=s.c[i] > base[1]))
    return rows


def intraday(which):
    dev, holdout = split_universe()
    tickers = dev if which == "dev" else holdout
    bars = load_bars()
    green, rs = market_green(bars), rs_top(bars)
    rng = np.random.default_rng(42)
    rows, skipped = [], 0
    cutoff = bars["close"].index[-1] - pd.Timedelta(days=725)
    for n, t in enumerate(tickers):
        s = Series(t, bars, green, rs)
        prior = _mark_prior_breakouts(s)
        recent = np.flatnonzero((s.dates >= cutoff) & np.isfinite(s.c))
        candidates = [i for i in recent[1:] if s.green[i - 1] and s.rs[i - 1] and s.h[i] > np.nanmax(s.h[i - BASE_MIN:i])
                      and find_base(s, i) is not None]
        if not candidates:
            continue
        hourly = load_hourly(t)
        if hourly is None:
            skipped += 1
            continue
        rows += intraday_ticker(s, hourly, prior)
        if n % 50 == 0:
            print(f"{n}/{len(tickers)}: {len(rows)} trades")
    df = pd.DataFrame(rows)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_DIR / f"trades_intraday_{which}.csv", index=False)
    daily = pd.read_csv(OUT_DIR / f"trades_{which}.csv", parse_dates=["date"]) if (OUT_DIR / f"trades_{which}.csv").exists() else None
    hdr = "| Slice | Trades | Win % | Expectancy (net R) | 95% CI (by month) |\n|---|---|---|---|---|"
    lines = [f"# Intraday entry — {which} set", "", f"{df.date.min():%Y-%m-%d} → {df.date.max():%Y-%m-%d}, 1h bars, {skipped} tickers without data.", "",
             hdr, _line("Intraday entries", df.r, df.date, rng),
             _line("…that closed above the trigger", df.r[df.closed_above], df.date[df.closed_above], rng),
             _line("…that failed by the close", df.r[~df.closed_above], df.date[~df.closed_above], rng)]
    if daily is not None:
        recent = daily[(daily.date >= df.date.min()) & (daily.kind == "breakout")]
        lines.append(_line("Daily-close breakouts, same period", recent.r, recent.date, rng))
    lines += ["", f"Median risk {df.risk_pct.median():.1%} of price. Mean return per trade {df.ret.mean():+.2%} of price, "
              f"median hold {df.days_held.median():.0f} days. Stopped out the same day: {(df.days_held == 0).mean():.0%}."]
    (OUT_DIR / f"report_intraday_{which}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


# ---------------------------------------------------------------- scanner

def scan():
    """Bases set up as of the last close, with trigger and undercut levels for the next session."""
    bars = load_bars()
    green, rs = market_green(bars), rs_top(bars)
    tickers = [c for c in bars["close"].columns if c not in MARKET]
    rows = []
    for t in tickers:
        s = Series(t, bars, green, rs)
        i = len(s.c)  # find_base looks at the bars before i, so this is the base as of the last close
        p = i - 1
        if not (np.isfinite(s.c[p]) and s.rs[p] and s.c[p] > MIN_PRICE and s.v[p] > MIN_VOLUME and s.adr20[p] >= MIN_ADR
                and s.c[p] > s.e8[p] and s.c[p] > s.e21[p] and s.c[p] > s.e50[p]):
            continue
        base = find_base(s, i)
        if base:
            rows.append(dict(ticker=t, close=round(s.c[p], 2), trigger=round(base[1], 2), undercut=round(base[2], 2),
                             base_days=base[0], adr_pct=round(s.adr20[p] * 100, 1), avg_volume=int(s.vol20[p])))
    last = bars["close"].index[-1]
    print(f"As of {last:%Y-%m-%d}. Market filter: {'GREEN' if green.iloc[-1] else 'NOT green, the rules take no new trades'}.")
    print(pd.DataFrame(rows).sort_values("avg_volume", ascending=False).to_string(index=False) if rows else "No setups.")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["fetch", "test", "intraday", "scan"])
    p.add_argument("--set", choices=["dev", "holdout"], default="dev")
    args = p.parse_args()
    if args.command == "fetch":
        fetch()
    elif args.command == "test":
        test(args.set)
    elif args.command == "intraday":
        intraday(args.set)
    else:
        scan()


if __name__ == "__main__":
    main()
