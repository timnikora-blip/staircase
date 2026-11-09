"""Staircase breakdown, the short side, and its one-shot tests (see Staircase_Short_Strategy.md).

Usage (from the trading folder):
    .venv\\Scripts\\python -m backtest.staircase_short smoke     # bug check, prints a few trades and no totals
    .venv\\Scripts\\python -m backtest.staircase_short test      # test A: outside the S&P 1500, 1h entries
    .venv\\Scripts\\python -m backtest.staircase_short daily     # test B: S&P 1500, 10 years, daily close
"""
import argparse
import logging
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

from . import momentum as m
from . import momentum_dashboard as md
from . import staircase as st

MIN_ADR = 0.03
EMA8_MAX_ABOVE = 0.03
BORROW = 0.03          # a year, of entry value
MIN_MONTHS = 12
THIRD = 1 / 3
TRIM_DOWN_DAYS = (2, 4)
BASE_RULES = ("leg", "range", "below_e50", "below_e21", "touches", "sell_volume")


# ---------------------------------------------------------------- rules

def market_red(bars):
    red = pd.Series(True, index=bars["close"].index)
    for t in m.MARKET:
        c = bars["close"][t]
        for span in (8, 21, 50):
            red &= c < m.ema(c, span)
    return red


def passes_screener(s, p):
    """The video's short screener on bar p, without market cap, which is applied per ticker."""
    if not np.isfinite(s.c[p] + s.e8[p] + s.e21[p] + s.adr20[p] + s.vol10[p]):
        return False
    return bool(s.c[p] > m.MIN_PRICE and s.vol10[p] > m.MIN_VOLUME and s.adr20[p] >= MIN_ADR
                and 0 <= s.e8[p] / s.c[p] - 1 <= EMA8_MAX_ABOVE and s.e21[p] > s.c[p])


def base_checks(s, i, n):
    """Each base rule for the n days before i, as ({rule: passed}, base low, base high)."""
    a = i - n
    adr_px = s.adr50[i - 1] * s.c[i - 1]
    hi, lo = np.max(s.h[a:i]), np.min(s.l[a:i])
    leg_drop = 1 - np.min(s.l[a - 5:a]) / np.max(s.h[a - m.POLE_LOOKBACK:a])
    touches = np.flatnonzero(s.l[a:i] <= lo + m.TOUCH_ADR * adr_px)
    b = a - 20
    chg = s.c[b:i] - s.c[b - 1:i - 1]
    vol = s.v[b:i]
    down, up = vol[chg < 0], vol[chg > 0]
    return dict(
        leg=not leg_drop < max(m.POLE_MIN_GAIN, m.POLE_ADR_MULT * s.adr50[i - 1]),
        range=bool(hi - lo <= m.BASE_RANGE_ADR * adr_px),
        below_e50=not hi > s.e50[i - 1],
        below_e21=not s.c[i - 1] >= s.e21[i - 1],
        touches=len(touches) >= 2 and touches[-1] - touches[0] >= 2,
        sell_volume=bool(len(down) and len(up) and np.mean(down) > np.mean(up)),
    ), lo, hi


def find_base(s, i):
    """Longest base before i passing the rules, as (N, low, high), or None."""
    if i < m.BASE_MAX + m.POLE_LOOKBACK + 25 or not np.isfinite(s.adr50[i - 1] + s.e50[i - 1]):
        return None
    if np.isnan(s.l[i - m.BASE_MAX - m.POLE_LOOKBACK]) or np.isnan(s.l[i - m.BASE_MAX - 21]):
        return None
    for n in range(m.BASE_MAX, m.BASE_MIN - 1, -1):
        checks, lo, hi = base_checks(s, i, n)
        if all(checks[k] for k in BASE_RULES):
            return n, lo, hi
    return None


def manage(s, start, entry, stop):
    """Cover per the rules from bar `start` on. Returns the legs [(bar, fraction, price)] and the exit reason."""
    left, downs, pending, legs, prev = 1.0, 0, False, [], None
    for k in range(start, len(s.o)):
        if np.isnan(s.c[k]):
            continue
        if pending:
            legs.append((k, left, s.o[k] * (1 + m.SLIPPAGE)))
            return legs, "ema_close"
        if s.o[k] >= stop:
            legs.append((k, left, s.o[k] * (1 + m.SLIPPAGE)))
            return legs, "stop"
        if s.h[k] >= stop:
            legs.append((k, left, stop * (1 + m.SLIPPAGE)))
            return legs, "stop"
        last_close = s.c[k - 1] if prev is None else prev
        if s.c[k] < last_close and s.c[k] < entry:
            downs += 1
            if downs in TRIM_DOWN_DAYS:
                legs.append((k, THIRD, s.c[k] * (1 + m.SLIPPAGE)))
                left -= THIRD
        prev = s.c[k]
        pending = s.c[k] > s.e8[k] and s.c[k] > s.e21[k]
    last = np.flatnonzero(np.isfinite(s.c))[-1]
    legs.append((last, left, s.c[last]))
    return legs, "open"


def manage_ema21(s, start, entry, stop):
    """Report-only exit: cover everything at the next open after a close above EMA21, with the stop live."""
    pending = False
    for k in range(start, len(s.o)):
        if np.isnan(s.c[k]):
            continue
        if pending or s.o[k] >= stop:
            return [(k, 1.0, s.o[k] * (1 + m.SLIPPAGE))]
        if s.h[k] >= stop:
            return [(k, 1.0, stop * (1 + m.SLIPPAGE))]
        pending = s.c[k] > s.e21[k]
    last = np.flatnonzero(np.isfinite(s.c))[-1]
    return [(last, 1.0, s.c[last])]


def r_multiple(s, i, legs, entry, risk):
    pnl = -2 * m.COMMISSION
    for k, f, px in legs:
        pnl += f * (entry - px) - f * entry * BORROW * (s.dates[k] - s.dates[i]).days / 365
    return pnl / (risk + 2 * m.COMMISSION)


def candidate_days(s, red, use_filter=True):
    out = []
    for i in range(m.BASE_MAX + m.POLE_LOOKBACK + 25, len(s.c)):
        p = i - 1
        if (use_filter and not red[p]) or not passes_screener(s, p) or not np.isfinite(s.l[i]):
            continue
        if s.l[i] >= np.nanmin(s.l[i - m.BASE_MIN:i]):
            continue
        base = find_base(s, i)
        if base is not None and s.l[i] < base[1]:
            out.append((i, base))
    return out


# ---------------------------------------------------------------- entries

def _trade(s, i, kind, entry, stop, base, legs, reason, atr, **extra):
    risk = stop - entry
    return dict(ticker=s.ticker, i=i, date=s.dates[i], kind=kind, base_days=base[0], trigger=base[1], entry=entry, stop=stop,
                risk_pct=risk / entry, stop_atr=risk / atr, volume=s.v[i], r=r_multiple(s, i, legs, entry, risk), reason=reason,
                exit_date=s.dates[legs[-1][0]], days_held=legs[-1][0] - i, ret=sum(f * (entry - px) for _, f, px in legs) / entry,
                legs=legs, **extra)


def hourly_trades(s, hourly, candidates):
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
        cum_vol, high_so_far, fired, best_fill = 0.0, -np.inf, None, None
        for n, b in enumerate(day.itertuples()):
            cum_vol += b.volume
            high_so_far = max(high_so_far, b.high)
            ok_vol = n < len(normal) and cum_vol >= m.BREAKOUT_RVOL * normal[n]
            if best_fill is None and b.low < base[1] and ok_vol:
                best_fill = (n, min(base[1], b.open) * (1 - m.SLIPPAGE), high_so_far)
            if b.close < base[1] and ok_vol:
                fired = n
                entry, stop = b.close * (1 - m.SLIPPAGE), high_so_far
                break
        if fired is None or stop <= entry or (stop - entry) / entry < st.MIN_RISK:
            continue
        rest = day.iloc[fired + 1:]
        if len(rest) and rest.high.max() >= stop:
            legs, reason = [(i, 1.0, stop * (1 + m.SLIPPAGE))], "stop"
            r21 = r_multiple(s, i, legs, entry, stop - entry)
        else:
            legs, reason = manage(s, i + 1, entry, stop)
            r21 = r_multiple(s, i, manage_ema21(s, i + 1, entry, stop), entry, stop - entry)
        r_best = np.nan
        if best_fill and best_fill[2] > best_fill[1] and (best_fill[2] - best_fill[1]) / best_fill[1] >= st.MIN_RISK:
            n, e2, s2 = best_fill
            later = day.iloc[n + 1:]
            if len(later) and later.high.max() >= s2:
                r_best = r_multiple(s, i, [(i, 1.0, s2 * (1 + m.SLIPPAGE))], e2, s2 - e2)
            else:
                r_best = r_multiple(s, i, manage(s, i + 1, e2, s2)[0], e2, s2 - e2)
        busy_until = legs[-1][0]
        rows.append(_trade(s, i, "hourly", entry, stop, base, legs, reason, s.atr[i - 1], r_ema21=r21, r_best_fill=r_best,
                           closed_below=bool(s.c[i] < base[1])))
    return rows


def daily_trades(s, red, use_filter=True):
    rows = []
    busy_until = -1
    for i in range(m.BASE_MAX + m.POLE_LOOKBACK + 25, len(s.c) - 1):
        p = i - 1
        if i <= busy_until or (use_filter and not red[p]) or not passes_screener(s, p) or not np.isfinite(s.c[i] + s.atr[i] + s.vol20[i]):
            continue
        if s.c[i] >= np.nanmin(s.l[i - m.BASE_MIN:i]) or s.v[i] < m.BREAKOUT_RVOL * s.vol20[i]:
            continue
        base = find_base(s, i)
        if base is None or s.c[i] >= base[1]:
            continue
        entry, stop = s.c[i] * (1 - m.SLIPPAGE), s.h[i]
        if stop <= entry or (stop - entry) / entry < st.MIN_RISK:
            continue
        legs, reason = manage(s, i + 1, entry, stop)
        r21 = r_multiple(s, i, manage_ema21(s, i + 1, entry, stop), entry, stop - entry)
        busy_until = legs[-1][0]
        rows.append(_trade(s, i, "daily", entry, stop, base, legs, reason, s.atr[i], r_ema21=r21))
    return rows


def add_control(s, rows, red, rng):
    if not rows:
        return
    pool = np.array([i for i in range(1, len(s.c) - 1) if red[i] and passes_screener(s, i) and np.isfinite(s.atr[i])])
    for row in rows:
        vals = []
        if len(pool):
            for i in rng.choice(pool, m.CONTROLS):
                entry = s.c[i] * (1 - m.SLIPPAGE)
                stop = entry + row["stop_atr"] * s.atr[i]
                legs, _ = manage(s, i + 1, entry, stop)
                vals.append(r_multiple(s, i, legs, entry, stop - entry))
        row["control_r"] = np.mean(vals) if vals else np.nan


# ---------------------------------------------------------------- portfolio

def run_portfolio(trades, bars):
    """Daily equity for short positions, marked to the close. Cash holds realised profit and loss."""
    dates = bars["close"].index
    first = min(t["i"] for t in trades)
    by_day = {}
    for t in sorted(trades, key=lambda x: (x["i"], -x["volume"])):
        by_day.setdefault(t["i"], []).append(t)
    close = {t: bars["close"][t].ffill().to_numpy() for t in {x["ticker"] for x in trades}}
    equity = np.ones(len(dates))
    exposure = np.zeros(len(dates))
    cash, open_pos, taken = 1.0, [], 0

    def settle(pos, d):
        nonlocal cash
        for k, frac, px in pos["legs"]:
            if k == d:
                days = (dates[k] - dates[pos["i"]]).days
                cash += pos["shares"] * frac * (pos["entry"] - px - pos["entry"] * BORROW * days / 365) - m.COMMISSION * pos["shares"] * frac
                pos["left"] -= frac

    for d in range(first, len(dates)):
        for pos in list(open_pos):
            settle(pos, d)
            if pos["left"] <= 1e-9:
                open_pos.remove(pos)
        value = lambda: cash + sum(p["shares"] * p["left"] * (p["entry"] - close[p["ticker"]][d]) for p in open_pos)
        for t in by_day.get(d, []):
            if len(open_pos) >= m.MAX_POSITIONS:
                break
            eq = value()
            shares = min(m.RISK_PER_TRADE * eq / (t["stop"] - t["entry"]), m.MAX_POSITION * eq / t["entry"])
            cash -= m.COMMISSION * shares
            pos = dict(ticker=t["ticker"], i=t["i"], entry=t["entry"], shares=shares, left=1.0, legs=t["legs"])
            taken += 1
            settle(pos, d)
            if pos["left"] > 1e-9:
                open_pos.append(pos)
        equity[d] = value()
        exposure[d] = sum(p["shares"] * p["left"] * close[p["ticker"]][d] for p in open_pos) / equity[d]
    curve = pd.Series(equity[first:], index=dates[first:])
    return curve, taken, float(exposure[first:].mean())


# ---------------------------------------------------------------- runs

def setup(bars):
    _, rs = st.sets_up(bars)
    return market_red(bars), rs


def make_series(t, bars, red, rs):
    return st.add_vol10(m.Series(t, bars, red, rs))


def run_hourly(tickers, bars, label, cap_filter=True, use_filter=True, with_control=True, seed=42):
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    red, rs = setup(bars)
    red_arr = red.to_numpy()
    cands = {}
    for n, t in enumerate(tickers):
        s = make_series(t, bars, red, rs)
        days = candidate_days(s, red_arr, use_filter)
        if days:
            cands[t] = (s, days)
        if n % 1000 == 0:
            print(f"{label}: scanned {n}/{len(tickers)}, {len(cands)} with candidates", flush=True)
    excluded = 0
    if cap_filter:
        caps = md.market_caps(list(cands))
        keep = {t: v for t, v in cands.items() if np.isfinite(caps.get(t, np.nan)) and caps[t] >= md.MIN_MARKET_CAP}
        excluded = len(cands) - len(keep)
        cands = keep
    print(f"{label}: {len(cands)} tickers with candidates, {excluded} under the cap floor or unknown", flush=True)
    names = list(cands)
    with ThreadPoolExecutor(6) as pool:
        hourly = dict(zip(names, pool.map(st.load_hourly, names)))
    rng = np.random.default_rng(seed)
    rows, missing = [], 0
    for t in names:
        s, days = cands[t]
        if hourly[t] is None:
            missing += 1
            continue
        tr = hourly_trades(s, hourly[t], days)
        if with_control:
            add_control(s, tr, red_arr, rng)
        rows += tr
    return rows, dict(tickers=len(tickers), with_candidates=len(names), excluded_by_cap=excluded, no_hourly=missing)


def summarize(rows, no_filter, bars, meta, name):
    """Same shape as staircase.summarize, so the dashboard reads both alike."""
    rng = np.random.default_rng(7)
    if not rows:
        return None, None
    df = pd.DataFrame(rows).dropna(subset=["control_r"]).sort_values("date").reset_index(drop=True)
    d = df.date
    months = int(d.dt.to_period("M").nunique())
    sig, ctl, diff = st.ci(df.r, d, rng), st.ci(df.control_r, d, rng), st.ci(df.r - df.control_r, d, rng)
    enough = months >= MIN_MONTHS
    passed = bool(sig["lo"] is not None and diff["lo"] is not None and sig["lo"] > 0 and diff["lo"] > 0)
    without_best = df.r.drop(df.r.idxmax())
    slices = {"Trades": sig, "Random entries, same days and stops": ctl,
              "Without the single best trade": st.ci(without_best, d[without_best.index], rng),
              "Market filter off": st.ci([t["r"] for t in no_filter], [t["date"] for t in no_filter], rng),
              "Cover all on a close above EMA21": st.ci(df.r_ema21, d, rng)}
    if "r_best_fill" in df:
        slices["Best-case fill at the trigger"] = st.ci(df.r_best_fill, d, rng)
        slices["Closed below the trigger"] = st.ci(df.r[df.closed_below], d[df.closed_below], rng)
        slices["Failed by the close"] = st.ci(df.r[~df.closed_below], d[~df.closed_below], rng)
    kept = [t for t in rows if np.isfinite(t["control_r"])]
    curve, taken, exposure = run_portfolio(kept, bars)
    spy = m._spy_total_return(curve.index)
    stats, sp = m.curve_stats(curve), m.curve_stats(spy)
    top = df.r.nlargest(max(1, len(df) // 20)).sum() / df.r.sum() if df.r.sum() > 0 else None
    return dict(
        name=name, meta=meta, enough_months=enough, passed=passed, signal=sig, control=ctl, diff=diff, slices=slices,
        start=f"{d.min():%Y-%m-%d}", end=f"{d.max():%Y-%m-%d}", months=months,
        median_r=float(df.r.median()), median_risk=float(df.risk_pct.median()), median_hold=float(df.days_held.median()),
        same_day_stop=float((df.days_held == 0).mean()), best=float(df.r.max()), worst=float(df.r.min()), top5_share=top,
        exits=[dict(reason=k, n=int(len(g)), r=float(g.r.mean())) for k, g in df.groupby("reason")],
        by_year=[dict(year=int(y), n=int(len(g)), r=float(g.r.mean()), control=float(g.control_r.mean())) for y, g in df.groupby(d.dt.year)],
        r_values=[round(float(x), 2) for x in df.r],
        portfolio=dict(taken=taken, exposure=exposure, strategy=stats, spy=sp, dates=[f"{x:%Y-%m-%d}" for x in curve.index[::2]],
                       curve=[round(float(x), 4) for x in curve.iloc[::2]], spy_curve=[round(float(x / spy.iloc[0]), 4) for x in spy.iloc[::2]]),
        trades=[dict(ticker=r.ticker, date=f"{r.date:%Y-%m-%d}", entry=round(float(r.entry), 2), stop=round(float(r.stop), 2),
                     risk=round(float(r.risk_pct), 4), r=round(float(r.r), 2), control=round(float(r.control_r), 2),
                     held=int(r.days_held), exit=r.reason) for r in df.itertuples()],
    ), df


def smoke():
    """Bug check on a few S&P 1500 tickers with the filter off. Prints trades, never totals."""
    bars = st.load_market()
    pool = sorted(st.sp1500_tickers() & set(bars["close"].columns))
    tickers = sorted(np.random.default_rng(2).permutation(pool)[:40])
    rows, meta = run_hourly(tickers, bars, "smoke", cap_filter=False, use_filter=False, with_control=False)
    print(meta)
    for t in rows[:6]:
        print({k: t[k] for k in ("ticker", "date", "trigger", "entry", "stop", "reason", "days_held", "closed_below")}, t["legs"])
    assert all(t["entry"] < t["stop"] and t["entry"] <= t["trigger"] for t in rows)
    assert all(abs(sum(f for _, f, _ in t["legs"]) - 1) < 1e-9 for t in rows)
    assert all(np.isfinite(t["r"]) for t in rows)
    assert all(t["days_held"] > 0 or t["reason"] == "stop" for t in rows)
    if rows:
        red, _ = setup(bars)
        curve, taken, exposure = run_portfolio(rows, bars)
        assert curve.notna().all() and taken > 0
    print("mechanics ok on", len(rows), "trades")


def test():
    bars = st.load_market()
    seen = st.sp1500_tickers() | set(m.MARKET)
    tickers = sorted(t for t in bars["close"].columns if t not in seen)
    rows, meta = run_hourly(tickers, bars, "short A")
    no_filter, _ = run_hourly(tickers, bars, "short A, filter off", use_filter=False, with_control=False)
    text = (f"{meta['tickers']} US common stocks outside the S&P 1500. {meta['with_candidates']} had candidates and passed the market cap floor, "
            f"{meta['excluded_by_cap']} were under it or unknown, {meta['no_hourly']} had no hourly bars.")
    if not rows:
        print("no trades")
        return
    summary, df = summarize(rows, no_filter, bars, text, "short_primary")
    st.write_outputs(summary, df, "short_primary")


def daily():
    bars = m.load_bars()
    red, rs = setup(bars)
    red_arr = red.to_numpy()
    listed = st.sp1500_tickers()
    tickers = [t for t in bars["close"].columns if t in listed]
    rng = np.random.default_rng(42)
    rows, no_filter = [], []
    for t in tickers:
        s = make_series(t, bars, red, rs)
        tr = daily_trades(s, red_arr)
        add_control(s, tr, red_arr, rng)
        rows += tr
        no_filter += daily_trades(s, red_arr, use_filter=False)
    text = f"{len(tickers)} S&P 1500 tickers over 10 years. Entry at the close of the breakdown day, stop at that day's high."
    summary, df = summarize(rows, no_filter, bars, text, "short_daily")
    st.write_outputs(summary, df, "short_daily")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["smoke", "test", "daily"])
    {"smoke": smoke, "test": test, "daily": daily}[p.parse_args().command]()


if __name__ == "__main__":
    main()
