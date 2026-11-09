"""Staircase breakout from the SRxTrades video, and its one-shot test (see Staircase_Strategy.md).

Usage (from the trading folder):
    .venv\\Scripts\\python -m backtest.staircase smoke        # bug check on used S&P 1500 tickers
    .venv\\Scripts\\python -m backtest.staircase test         # primary test, run once
    .venv\\Scripts\\python -m backtest.staircase replicate    # S&P 1500, 10 years, daily-close entry
"""
import argparse
import json
import logging
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from . import momentum as m
from . import momentum_dashboard as md

OUT_DIR = Path("results/staircase")
HOURLY_DIR = md.MARKET_DIR / "1h"
BASE_RULES = ("pole", "range", "above_e50", "above_e21", "touches")
MIN_RISK = 0.005
SMOKE_TICKERS = 60


# ---------------------------------------------------------------- rules

def add_vol10(s):
    s.vol10 = pd.Series(s.v).rolling(10).mean().to_numpy()
    return s


def make_series(ticker, bars, green, rs):
    return add_vol10(m.Series(ticker, bars, green, rs))


def passes_screener(s, p):
    """The video's screener on bar p, without market cap, which is applied per ticker."""
    return bool(np.isfinite(s.c[p] + s.e21[p] + s.e50[p] + s.adr20[p] + s.vol10[p])
                and s.c[p] > m.MIN_PRICE and s.vol10[p] > m.MIN_VOLUME and s.adr20[p] >= m.MIN_ADR
                and s.c[p] > s.e21[p] and s.c[p] > s.e50[p])


def find_base(s, i):
    """Longest base ending the day before i that passes the video's rules, as (N, high, low), or None."""
    if i < m.BASE_MAX + m.POLE_LOOKBACK + 5 or not np.isfinite(s.adr50[i - 1] + s.e50[i - 1]):
        return None
    if np.isnan(s.l[i - m.BASE_MAX - m.POLE_LOOKBACK]):
        return None
    for n in range(m.BASE_MAX, m.BASE_MIN - 1, -1):
        checks, hi, lo = m.base_checks(s, i, n)
        if all(checks[k] for k in BASE_RULES):
            return n, hi, lo
    return None


def manage_ema21(s, start, entry, stop):
    """Report-only exit: everything at the next open after a close below EMA21, with the stop live."""
    pending = False
    for k in range(start, len(s.o)):
        if np.isnan(s.c[k]):
            continue
        if pending:
            return [(k, 1.0, s.o[k] * (1 - m.SLIPPAGE))]
        if s.o[k] <= stop:
            return [(k, 1.0, s.o[k] * (1 - m.SLIPPAGE))]
        if s.l[k] <= stop:
            return [(k, 1.0, stop * (1 - m.SLIPPAGE))]
        pending = s.c[k] < s.e21[k]
    last = np.flatnonzero(np.isfinite(s.c))[-1]
    return [(last, 1.0, s.c[last])]


def candidate_days(s, first=1):
    """Bars where the prior close passes the market filter and screener and the day trades above a base high."""
    out = []
    for i in range(max(first, m.BASE_MAX + m.POLE_LOOKBACK + 5), len(s.c)):
        p = i - 1
        if not s.green[p] or not passes_screener(s, p) or not np.isfinite(s.h[i]):
            continue
        if s.h[i] <= np.nanmax(s.h[i - m.BASE_MIN:i]):
            continue
        base = find_base(s, i)
        if base is not None and s.h[i] > base[1]:
            out.append((i, base))
    return out


# ---------------------------------------------------------------- entries

def _trade(s, i, kind, entry, stop, base, legs, reason, atr, **extra):
    risk = entry - stop
    return dict(ticker=s.ticker, i=i, date=s.dates[i], kind=kind, base_days=base[0], trigger=base[1], entry=entry, stop=stop,
                risk_pct=risk / entry, stop_atr=risk / atr, volume=s.v[i], r=m.r_multiple(legs, entry, risk), reason=reason,
                exit_date=s.dates[legs[-1][0]], days_held=legs[-1][0] - i, ret=sum(f * (px - entry) for _, f, px in legs) / entry,
                legs=legs, **extra)


def hourly_trades(s, hourly, candidates):
    """Primary rule: first hourly close above the trigger on volume pace, stop at the low of the day so far."""
    rows = []
    by_day = {d: g for d, g in hourly.groupby(hourly.index.tz_localize(None).normalize())}
    cum = pd.DataFrame({d: g.volume.cumsum().reset_index(drop=True) for d, g in by_day.items()}).T.sort_index()
    pace = cum.rolling(20, min_periods=10).mean().shift(1)
    busy_until = -1
    for i, base in candidates:
        if i <= busy_until or s.dates[i] not in by_day or not np.isfinite(s.atr[i - 1]):
            continue
        day = by_day[s.dates[i]]
        normal = pace.loc[s.dates[i]].to_numpy()
        cum_vol, low_so_far, fired = 0.0, np.inf, None
        best_fill = None
        for n, b in enumerate(day.itertuples()):
            cum_vol += b.volume
            low_so_far = min(low_so_far, b.low)
            ok_vol = n < len(normal) and cum_vol >= m.BREAKOUT_RVOL * normal[n]
            if best_fill is None and b.high > base[1] and ok_vol:
                best_fill = (n, max(base[1], b.open) * (1 + m.SLIPPAGE), low_so_far)
            if b.close > base[1] and ok_vol:
                fired = n
                entry, stop = b.close * (1 + m.SLIPPAGE), low_so_far
                break
        if fired is None or entry <= stop or (entry - stop) / entry < MIN_RISK:
            continue
        rest = day.iloc[fired + 1:]
        if len(rest) and rest.low.min() <= stop:
            legs, reason = [(i, 1.0, stop * (1 - m.SLIPPAGE))], "stop"
            r21 = m.r_multiple(legs, entry, entry - stop)
        else:
            legs, reason = m.manage(s, i + 1, entry, stop)
            r21 = m.r_multiple(manage_ema21(s, i + 1, entry, stop), entry, entry - stop)
        r_best = np.nan
        if best_fill and best_fill[1] > best_fill[2] and (best_fill[1] - best_fill[2]) / best_fill[1] >= MIN_RISK:
            n, e2, s2 = best_fill
            later = day.iloc[n + 1:]
            if len(later) and later.low.min() <= s2:
                r_best = m.r_multiple([(i, 1.0, s2 * (1 - m.SLIPPAGE))], e2, e2 - s2)
            else:
                r_best = m.r_multiple(m.manage(s, i + 1, e2, s2)[0], e2, e2 - s2)
        busy_until = legs[-1][0]
        rows.append(_trade(s, i, "hourly", entry, stop, base, legs, reason, s.atr[i - 1], r_ema21=r21, r_best_fill=r_best,
                           closed_above=bool(s.c[i] > base[1])))
    return rows


def daily_trades(s):
    """Replication rule: enter at the close of a breakout day on 1.5× volume, stop at that day's low."""
    rows = []
    busy_until = -1
    for i in range(m.BASE_MAX + m.POLE_LOOKBACK + 5, len(s.c) - 1):
        p = i - 1
        if i <= busy_until or not s.green[p] or not passes_screener(s, p) or not np.isfinite(s.c[i] + s.atr[i] + s.vol20[i]):
            continue
        if s.c[i] <= np.nanmax(s.h[i - m.BASE_MIN:i]) or s.v[i] < m.BREAKOUT_RVOL * s.vol20[i]:
            continue
        base = find_base(s, i)
        if base is None or s.c[i] <= base[1]:
            continue
        entry, stop = s.c[i] * (1 + m.SLIPPAGE), s.l[i]
        if entry <= stop or (entry - stop) / entry < MIN_RISK:
            continue
        legs, reason = m.manage(s, i + 1, entry, stop)
        r21 = m.r_multiple(manage_ema21(s, i + 1, entry, stop), entry, entry - stop)
        busy_until = legs[-1][0]
        rows.append(_trade(s, i, "daily", entry, stop, base, legs, reason, s.atr[i], r_ema21=r21))
    return rows


def add_control(s, rows, rng):
    """Random entries at the close on days passing the market filter and screener, same stop in ATR, same exits."""
    if not rows:
        return
    pool = np.array([i for i in range(1, len(s.c) - 1) if s.green[i] and passes_screener(s, i) and np.isfinite(s.atr[i])])
    for row in rows:
        vals = []
        if len(pool):
            for i in rng.choice(pool, m.CONTROLS):
                entry = s.c[i] * (1 + m.SLIPPAGE)
                stop = entry - row["stop_atr"] * s.atr[i]
                if stop > 0:
                    legs, _ = m.manage(s, i + 1, entry, stop)
                    vals.append(m.r_multiple(legs, entry, entry - stop))
        row["control_r"] = np.mean(vals) if vals else np.nan


# ---------------------------------------------------------------- data

def load_hourly(ticker):
    import yfinance as yf

    path = HOURLY_DIR / f"{ticker}_1h.csv"
    if path.exists():
        df = pd.read_csv(path, index_col=0)
    else:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                df = yf.download(ticker, period="730d", interval="1h", auto_adjust=False, prepost=False,
                                 progress=False, multi_level_index=False, threads=False)
            except Exception:
                return None
        if df is None or df.empty:
            return None
        df.columns = [c.lower() for c in df.columns]
        df = df[["open", "high", "low", "close", "volume"]].dropna()
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path)
    if df.empty:
        return None
    df.index = pd.to_datetime(df.index, utc=True).tz_convert("America/New_York")
    return df


def load_market():
    """Whole-market bars without a last session most tickers don't have yet. Yahoo fills it in over several hours."""
    bars = pd.read_pickle(md.MARKET_DIR / "bars.pkl.gz")
    close = bars["close"]
    if close.iloc[-1].notna().sum() < 0.9 * close.iloc[-2].notna().sum():
        bars = {f: df.iloc[:-1] for f, df in bars.items()}
    return bars


def sp1500_tickers():
    return set(pd.read_csv(m.DATA_DIR / "universe.csv")["ticker"])


def sets_up(bars):
    green = m.market_green(bars)
    rs = pd.DataFrame(True, index=bars["close"].index, columns=bars["close"].columns)
    return green, rs


def run_hourly(tickers, bars, label, cap_filter=True):
    """Trades on the given tickers. Market cap and hourly bars are only fetched for tickers with candidates."""
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    green, rs = sets_up(bars)
    cands = {}
    for n, t in enumerate(tickers):
        s = make_series(t, bars, green, rs)
        days = candidate_days(s)
        if days:
            cands[t] = (s, days)
        if n % 500 == 0:
            print(f"{label}: scanned {n}/{len(tickers)}, {len(cands)} with candidates", flush=True)
    print(f"{label}: {len(cands)} tickers with candidate days", flush=True)
    excluded = 0
    if cap_filter:
        caps = md.market_caps(list(cands))
        keep = {t: v for t, v in cands.items() if np.isfinite(caps.get(t, np.nan)) and caps[t] >= md.MIN_MARKET_CAP}
        excluded = len(cands) - len(keep)
        cands = keep
        print(f"{label}: {len(cands)} tickers over the market cap floor, {excluded} under it or unknown", flush=True)
    names = list(cands)
    with ThreadPoolExecutor(6) as pool:
        hourly = {}
        for n, (t, df) in enumerate(zip(names, pool.map(load_hourly, names))):
            hourly[t] = df
            if n % 200 == 0:
                print(f"{label}: hourly bars {n}/{len(names)}", flush=True)
    rng = np.random.default_rng(42)
    rows, missing = [], 0
    for t in names:
        s, days = cands[t]
        if hourly[t] is None:
            missing += 1
            continue
        tr = hourly_trades(s, hourly[t], days)
        add_control(s, tr, rng)
        rows += tr
    return rows, dict(tickers=len(tickers), with_candidates=len(names), excluded_by_cap=excluded, no_hourly=missing)


# ---------------------------------------------------------------- portfolio

def run_portfolio(trades, bars):
    """Daily equity. Unlike momentum.run_portfolio, a position can open and exit on the same day."""
    dates = bars["close"].index
    first = min(t["i"] for t in trades)
    by_day = {}
    for t in sorted(trades, key=lambda x: (x["i"], -x["volume"])):
        by_day.setdefault(t["i"], []).append(t)
    close = {t: bars["close"][t].ffill().to_numpy() for t in {x["ticker"] for x in trades}}
    equity = np.ones(len(dates))
    cash, open_pos, taken = 1.0, [], 0
    exposure = np.zeros(len(dates))

    def settle(pos, d):
        nonlocal cash
        for k, frac, px in pos["legs"]:
            if k == d:
                cash += pos["shares"] * frac * px - m.COMMISSION * pos["shares"] * frac
                pos["left"] -= frac

    for d in range(first, len(dates)):
        for pos in list(open_pos):
            settle(pos, d)
            if pos["left"] <= 1e-9:
                open_pos.remove(pos)
        value = lambda: cash + sum(p["shares"] * p["left"] * close[p["ticker"]][d] for p in open_pos)
        for t in by_day.get(d, []):
            if len(open_pos) >= m.MAX_POSITIONS:
                break
            eq = value()
            shares = min(m.RISK_PER_TRADE * eq / (t["entry"] - t["stop"]), m.MAX_POSITION * eq / t["entry"])
            cost = shares * t["entry"]
            if cost > cash:
                continue
            cash -= cost + m.COMMISSION * shares
            pos = dict(ticker=t["ticker"], shares=shares, left=1.0, legs=t["legs"])
            taken += 1
            settle(pos, d)
            if pos["left"] > 1e-9:
                open_pos.append(pos)
        equity[d] = value()
        exposure[d] = 1 - cash / equity[d]
    curve = pd.Series(equity[first:], index=dates[first:])
    return curve, taken, float(exposure[first:].mean())


# ---------------------------------------------------------------- report

def ci(r, dates, rng):
    r = np.asarray(r, float)
    keep = np.isfinite(r)
    if keep.sum() == 0 or len(set(pd.DatetimeIndex(dates)[keep].to_period("M"))) < 3:
        return dict(n=int(keep.sum()), win=None, mean=None, lo=None, hi=None)
    mean, lo, hi = m.month_ci(r[keep], pd.DatetimeIndex(dates)[keep], rng)
    return dict(n=int(keep.sum()), win=float((r[keep] > 0).mean()), mean=float(mean), lo=float(lo), hi=float(hi))


def summarize(rows, bars, meta, name):
    rng = np.random.default_rng(7)
    df = pd.DataFrame(rows).dropna(subset=["control_r"]).sort_values("date").reset_index(drop=True)
    d = df.date
    sig, ctl = ci(df.r, d, rng), ci(df.control_r, d, rng)
    diff = ci(df.r - df.control_r, d, rng)
    passed = sig["lo"] > 0 and diff["lo"] > 0
    without_best = df.r.drop(df.r.idxmax())
    slices = {"Trades": sig, "Random entries, same days and stops": ctl,
              "Without the single best trade": ci(without_best, d[without_best.index], rng),
              "Exit all on a close below EMA21": ci(df.r_ema21, d, rng)}
    if "r_best_fill" in df:
        slices["Best-case fill at the trigger"] = ci(df.r_best_fill, d, rng)
        slices["Closed above the trigger"] = ci(df.r[df.closed_above], d[df.closed_above], rng)
        slices["Failed by the close"] = ci(df.r[~df.closed_above], d[~df.closed_above], rng)
    kept = [t for t in rows if np.isfinite(t["control_r"])]  # the same trades as the statistics above
    curve, taken, exposure = run_portfolio(kept, bars)
    spy = m._spy_total_return(curve.index)
    st, sp = m.curve_stats(curve), m.curve_stats(spy)
    top = df.r.nlargest(max(1, len(df) // 20)).sum() / df.r.sum() if df.r.sum() > 0 else None
    return dict(
        name=name, meta=meta, passed=bool(passed), signal=sig, control=ctl, diff=diff, slices=slices,
        start=f"{d.min():%Y-%m-%d}", end=f"{d.max():%Y-%m-%d}", months=int(d.dt.to_period("M").nunique()),
        median_r=float(df.r.median()), median_risk=float(df.risk_pct.median()), median_hold=float(df.days_held.median()),
        same_day_stop=float((df.days_held == 0).mean()), best=float(df.r.max()), worst=float(df.r.min()), top5_share=top,
        exits=[dict(reason=k, n=int(len(g)), r=float(g.r.mean())) for k, g in df.groupby("reason")],
        by_year=[dict(year=int(y), n=int(len(g)), r=float(g.r.mean()), control=float(g.control_r.mean()))
                 for y, g in df.groupby(d.dt.year)],
        r_values=[round(float(x), 2) for x in df.r],
        portfolio=dict(taken=taken, exposure=exposure, strategy=st, spy=sp,
                       dates=[f"{x:%Y-%m-%d}" for x in curve.index[::2]],
                       curve=[round(float(x), 4) for x in curve.iloc[::2]],
                       spy_curve=[round(float(x / spy.iloc[0]), 4) for x in spy.iloc[::2]]),
        trades=[dict(ticker=r.ticker, date=f"{r.date:%Y-%m-%d}", entry=round(float(r.entry), 2), stop=round(float(r.stop), 2),
                     risk=round(float(r.risk_pct), 4), r=round(float(r.r), 2), control=round(float(r.control_r), 2),
                     held=int(r.days_held), exit=r.reason) for r in df.itertuples()],
    ), df


def write_outputs(summary, df, name):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.drop(columns="legs").to_csv(OUT_DIR / f"trades_{name}.csv", index=False)
    (OUT_DIR / f"summary_{name}.json").write_text(json.dumps(summary), encoding="utf-8")
    fmt = lambda x: "" if x is None else f"{x:+.3f}"
    lines = [f"# Staircase test — {name}", "",
             f"{summary['meta']}", f"{summary['start']} → {summary['end']}, {summary['months']} months. Rules: {'Staircase_Short_Strategy.md' if name.startswith('short') else 'Staircase_Strategy.md'}.", "",
             f"**Success criteria met: {'YES' if summary['passed'] else 'NO'}**", "",
             f"Signal minus random: {fmt(summary['diff']['mean'])}R, 95% CI {fmt(summary['diff']['lo'])} … {fmt(summary['diff']['hi'])}", "",
             "| Slice | Trades | Win % | Expectancy (net R) | 95% CI (by month) |", "|---|---|---|---|---|"]
    for k, v in summary["slices"].items():
        win = "" if v["win"] is None else f"{v['win']:.0%}"
        lines.append(f"| {k} | {v['n']} | {win} | {fmt(v['mean'])} | {fmt(v['lo'])} … {fmt(v['hi'])} |")
    p = summary["portfolio"]
    lines += ["", f"Median R {summary['median_r']:+.2f}, median risk {summary['median_risk']:.1%} of price, median hold {summary['median_hold']:.0f} days, "
              f"same-day stop {summary['same_day_stop']:.0%}, best {summary['best']:+.1f}R, worst {summary['worst']:+.1f}R.", "",
              "| Exit | Trades | Avg R |", "|---|---|---|"]
    lines += [f"| {e['reason']} | {e['n']} | {e['r']:+.2f} |" for e in summary["exits"]]
    lines += ["", f"Portfolio: {p['taken']} trades, {p['exposure']:.0%} invested on average. "
              f"Strategy CAGR {p['strategy']['cagr']:+.1%}, drawdown {p['strategy']['max_dd']:.1%}, Sharpe {p['strategy']['sharpe']:.2f}. "
              f"SPY CAGR {p['spy']['cagr']:+.1%}, drawdown {p['spy']['max_dd']:.1%}, Sharpe {p['spy']['sharpe']:.2f}.", "",
              "| Year | Trades | Expectancy | Random |", "|---|---|---|---|"]
    lines += [f"| {y['year']} | {y['n']} | {y['r']:+.3f} | {y['control']:+.3f} |" for y in summary["by_year"]]
    text = "\n".join(lines) + "\n"
    (OUT_DIR / f"report_{name}.md").write_text(text, encoding="utf-8")
    print(text)


def smoke():
    """Bug check only, on used S&P 1500 tickers, so nothing from the fresh universe is seen."""
    bars = load_market()
    pool = sorted(sp1500_tickers() & set(bars["close"].columns))
    tickers = sorted(np.random.default_rng(1).permutation(pool)[:SMOKE_TICKERS])
    rows, meta = run_hourly(tickers, bars, "smoke", cap_filter=False)
    print(meta, f"trades: {len(rows)}")
    for t in rows[:6]:
        print({k: t[k] for k in ("ticker", "date", "trigger", "entry", "stop", "r", "reason", "days_held", "closed_above")}, t["legs"][:3])
    df = pd.DataFrame(rows)
    assert (df.entry > df.stop).all() and (df.risk_pct >= MIN_RISK).all()
    assert (df.entry >= df.trigger).all(), "entries must be above the trigger"
    assert (df.r >= -6).all(), df.sort_values("r").head()
    legs_ok = all(abs(sum(f for _, f, _ in t["legs"]) - 1) < 1e-9 for t in rows)
    print("leg fractions sum to 1:", legs_ok)
    curve, taken, exposure = run_portfolio(rows, bars)
    print(f"portfolio ok: {taken} taken, final {curve.iloc[-1]:.3f}, exposure {exposure:.0%}, min {curve.min():.3f}")


def test():
    bars = load_market()
    seen =sp1500_tickers() | set(m.MARKET)
    tickers = sorted(t for t in bars["close"].columns if t not in seen)
    rows, meta = run_hourly(tickers, bars, "primary")
    text = (f"{meta['tickers']} US common stocks outside the S&P 1500. {meta['with_candidates']} had candidates and passed the market cap floor, "
            f"{meta['excluded_by_cap']} were under it or unknown, {meta['no_hourly']} had no hourly bars.")
    summary, df = summarize(rows, bars, text, "primary")
    write_outputs(summary, df, "primary")


def replicate():
    bars = m.load_bars()
    green, rs = sets_up(bars)
    listed = sp1500_tickers()
    tickers = [t for t in bars["close"].columns if t in listed]
    rng = np.random.default_rng(42)
    rows = []
    for t in tickers:
        s = make_series(t, bars, green, rs)
        tr = daily_trades(s)
        add_control(s, tr, rng)
        rows += tr
    text = f"{len(tickers)} S&P 1500 tickers, used in earlier tests, so this is supporting evidence only. Entry at the daily close. No market cap filter is needed for index members."
    summary, df = summarize(rows, bars, text, "replication")
    write_outputs(summary, df, "replication")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["smoke", "test", "replicate"])
    {"smoke": smoke, "test": test, "replicate": replicate}[p.parse_args().command]()


if __name__ == "__main__":
    main()
