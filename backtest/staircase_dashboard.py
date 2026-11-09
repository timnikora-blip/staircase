"""Staircase Breakout dashboard: playbook, whole-market watchlist, and the backtest. Writes staircase_dashboard.html.

Usage (from the trading folder), each morning before the open:
    .venv\\Scripts\\python -m backtest.staircase_dashboard
    .venv\\Scripts\\python -m backtest.staircase_dashboard --no-refresh     # reuse the last download

Rules and test plan: Staircase_Strategy.md. Test results come from results/staircase/.
"""
import argparse
import json
import webbrowser
from pathlib import Path

import numpy as np
import pandas as pd

from . import momentum as m
from . import momentum_dashboard as md
from . import staircase as st
from . import staircase_short as ss

TEMPLATE = Path(__file__).with_name("staircase_dashboard_template.html")
RESULTS = st.OUT_DIR
MIN_RULES_SHOWN = 4
RULES = dict(
    pole=md.RULES["pole"],
    range=md.RULES["range"],
    touches=md.RULES["touches"],
    above_e50=md.RULES["above_e50"],
    above_e21=md.RULES["above_e21"],
)
SHORT_RULES = dict(
    leg=f"Prior leg down of at least {m.POLE_MIN_GAIN:.0%} or {m.POLE_ADR_MULT:.0f}× ADR",
    range=f"Base range within {m.BASE_RANGE_ADR}× ADR",
    touches="Trigger level tested at least twice",
    below_e50="Base high stays below EMA50",
    below_e21="Close below EMA21",
    sell_volume="Volume heavier on down days than up days",
)
# From results/momentum/report_holdout.md, the earlier test of the stricter rules.
EARLIER = dict(trades=375, mean=0.094, lo=-0.18, hi=0.39, diff=0.145, diff_lo=-0.16, diff_hi=0.46, cagr=0.027, spy=0.14)


def best_base(s, i):
    best = None
    for n in range(m.BASE_MAX, m.BASE_MIN - 1, -1):
        checks, hi, lo = m.base_checks(s, i, n)
        checks = {k: checks[k] for k in RULES}
        if best is None or sum(checks.values()) > sum(best[1].values()):
            best = (n, checks, hi, lo)
    return best


def notes_for(row, green):
    t, a = row["trigger"], row["atr"]
    notes = []
    if row["pinned"]:
        notes.append(f"Possible takeover: it jumped at least {md.PIN_MIN_JUMP:.0%} in one day within the last {md.PIN_JUMP_DAYS} sessions and has barely moved since. "
                     "Check the news first. A stock held near a deal price isn't a coiled base.")
    if not green:
        notes.append("NO NEW TRADE while the market filter is off: SPY and QQQ must both close above their 8, 21 and 50 EMAs.")
    if row["missing"]:
        notes.append("Not a setup yet. Missing: " + "; ".join(row["missing"]) + ". Levels below are the nearest base and will move.")
    notes += [
        f"Set an alert at {md._p(t)}. Don't buy inside the base.",
        f"Entry: on the 5 minute chart, buy as it clears {md._p(t)} with volume running at least {m.BREAKOUT_RVOL}× normal, about {row['breakout_volume']:,} shares for a full day.",
        f"Stop: low of the day at entry. Size with the calculator in the Playbook tab. ATR is {md._p(a)}, so a stop far wider than that means a smaller position.",
        f"First trim: sell a quarter at +{m.TARGET_R:.0f}R, then move the stop to breakeven. The video gives no exit, so this rule is an assumption.",
        f"After the first trim: a quarter on a close below EMA8 (now {md._p(row['e8'])}), a quarter on a close below EMA21 (now {md._p(row['e21'])}), each at the next open.",
        f"Sell everything on a close below EMA50 (now {md._p(row['e50'])}), at the next open. This applies from day one.",
        "The rules don't cover earnings, so check the date before holding through one. Log the trade whether you take it or not.",
    ]
    return notes


def scan(bars):
    names = pd.read_csv(md.MARKET_DIR / "universe.csv", keep_default_na=False).set_index("ticker")["name"].to_dict()
    green, rs = st.sets_up(bars)
    rank = m.rs_rank(bars).iloc[-1]
    found = {}
    screened = 0
    for t in [c for c in bars["close"].columns if c not in m.MARKET]:
        s = st.make_series(t, bars, green, rs)
        i = len(s.c)
        p = i - 1
        if not st.passes_screener(s, p) or not np.isfinite(s.atr[p]) or i < md.MIN_BARS or np.isnan(s.l[i - m.BASE_MAX - m.POLE_LOOKBACK]):
            continue
        screened += 1
        best = best_base(s, i)
        if sum(best[1].values()) >= MIN_RULES_SHOWN:
            found[t] = (s, best)
    caps = md.market_caps(list(found))
    rows = []
    for t, (s, (n, checks, hi, lo)) in found.items():
        cap = caps.get(t, np.nan)
        if cap < md.MIN_MARKET_CAP:
            continue
        p = len(s.c) - 1
        missing = [RULES[k] for k, ok in checks.items() if not ok]
        row = dict(ticker=t, name=names.get(t, ""), market_cap=None if np.isnan(cap) else cap, close=s.c[p], trigger=hi, undercut=lo,
                   to_trigger=hi / s.c[p] - 1, base_days=n, atr=s.atr[p], adr=s.adr20[p], rs=None if np.isnan(rank.get(t, np.nan)) else float(rank[t]),
                   avg_volume=int(s.vol10[p]), breakout_volume=int(m.BREAKOUT_RVOL * s.vol20[p]), e8=s.e8[p], e21=s.e21[p], e50=s.e50[p],
                   passed=sum(checks.values()), total=len(checks), missing=missing,
                   checks=[[RULES[k], bool(ok)] for k, ok in checks.items()], chart=md.chart_data(s))
        row["pinned"] = md.looks_pinned(s)
        row["status"] = "Possibly pinned" if row["pinned"] else "Ready" if not missing else "One rule short"
        row["notes"] = notes_for(row, bool(green.iloc[-1]))
        rows.append(row)
    rows.sort(key=lambda r: (r["pinned"], -r["passed"], r["to_trigger"] < 0, abs(r["to_trigger"])))
    market = []
    for t in m.MARKET:
        c = bars["close"][t]
        market.append(dict(ticker=t, close=float(c.iloc[-1]), emas=[[f"EMA{w}", float(m.ema(c, w).iloc[-1])] for w in (8, 21, 50)]))
    calendar = bars["close"].index
    return dict(as_of=f"{calendar[-1]:%Y-%m-%d}", green=bool(green.iloc[-1]), market=market, scanned=bars["close"].shape[1] - len(m.MARKET),
                screened=screened, dates=[f"{d:%Y-%m-%d}" for d in calendar[-md.CHART_BARS:]], rows=rows)


def short_notes(row, red):
    t, h = row["trigger"], row["undercut"]
    notes = []
    if not red:
        notes.append("NO NEW TRADE while the market filter is off: SPY and QQQ must both close below their 8, 21 and 50 EMAs.")
    if row["missing"]:
        notes.append("Not a setup yet. Missing: " + "; ".join(row["missing"]) + ". Levels below are the nearest base and will move.")
    notes += [
        f"Check that shares can be borrowed, and what it costs, before the session. Set an alert at {md._p(t)}.",
        f"Entry: on the 5 minute chart, short the moment it breaks {md._p(t)} with volume running at least {m.BREAKOUT_RVOL}× normal, about {row['breakout_volume']:,} shares for a full day.",
        f"Stop: high of the day at entry, and it stays there. A gap can jump past a stop, so a loss can exceed the planned risk. ATR is {md._p(row['atr'])}.",
        "Trim: cover a third at the close of the 2nd down day and another at the close of the 4th. The video says one or two down days and gives no sizes, so these are assumptions.",
        f"Cover the rest at the next open after a close above both EMA8 (now {md._p(row['e8'])}) and EMA21 (now {md._p(row['e21'])}).",
        "The rules don't cover earnings, so check the date before holding through one. Log the trade whether you take it or not.",
    ]
    return notes


def scan_short(bars):
    names = pd.read_csv(md.MARKET_DIR / "universe.csv", keep_default_na=False).set_index("ticker")["name"].to_dict()
    red, rs = ss.setup(bars)
    rank = m.rs_rank(bars).iloc[-1]
    is_red = bool(red.iloc[-1])
    found, screened = {}, 0
    for t in [c for c in bars["close"].columns if c not in m.MARKET]:
        s = ss.make_series(t, bars, red, rs)
        i = len(s.c)
        p = i - 1
        if not ss.passes_screener(s, p) or not np.isfinite(s.atr[p]) or i < m.BASE_MAX + m.POLE_LOOKBACK + 25:
            continue
        if np.isnan(s.l[i - m.BASE_MAX - m.POLE_LOOKBACK]) or np.isnan(s.l[i - m.BASE_MAX - 21]):
            continue
        screened += 1
        best = None
        for n in range(m.BASE_MAX, m.BASE_MIN - 1, -1):
            checks, lo, hi = ss.base_checks(s, i, n)
            checks = {k: checks[k] for k in SHORT_RULES}
            if best is None or sum(checks.values()) > sum(best[1].values()):
                best = (n, checks, lo, hi)
        if sum(best[1].values()) >= len(SHORT_RULES) - 1:
            found[t] = (s, best)
    caps = md.market_caps(list(found))
    rows = []
    for t, (s, (n, checks, lo, hi)) in found.items():
        cap = caps.get(t, np.nan)
        if cap < md.MIN_MARKET_CAP:
            continue
        p = len(s.c) - 1
        missing = [SHORT_RULES[k] for k, ok in checks.items() if not ok]
        row = dict(side="short", ticker=t, name=names.get(t, ""), market_cap=None if np.isnan(cap) else cap, close=s.c[p], trigger=lo, undercut=hi,
                   to_trigger=lo / s.c[p] - 1, base_days=n, atr=s.atr[p], adr=s.adr20[p], rs=None if np.isnan(rank.get(t, np.nan)) else float(rank[t]),
                   avg_volume=int(s.vol10[p]), breakout_volume=int(m.BREAKOUT_RVOL * s.vol20[p]), e8=s.e8[p], e21=s.e21[p], e50=s.e50[p],
                   passed=sum(checks.values()), total=len(checks), missing=missing,
                   checks=[[SHORT_RULES[k], bool(ok)] for k, ok in checks.items()], chart=md.chart_data(s))
        row["status"] = "Ready" if not missing else "One rule short"
        row["notes"] = short_notes(row, is_red)
        rows.append(row)
    rows.sort(key=lambda r: (-r["passed"], r["to_trigger"] > 0, abs(r["to_trigger"])))
    return dict(rows=rows, red=is_red, screened=screened)


def load_summary(name):
    path = RESULTS / f"summary_{name}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--no-refresh", action="store_true", help="use the last download (a refresh takes several minutes)")
    p.add_argument("--out", default="staircase_dashboard.html")
    p.add_argument("--no-open", action="store_true", help="don't open the page in the browser")
    p.add_argument("--cloud", action="store_true", help="built by the GitHub workflow, which refreshes it on a schedule")
    args = p.parse_args()
    if not args.no_refresh:
        md.fetch_market()
    bars = st.load_market()
    data = scan(bars)
    short = scan_short(bars)
    short.update(primary=load_summary("short_primary"), replication=load_summary("short_daily"))
    data["short"] = short
    data.update(generated=f"{pd.Timestamp.now(tz='America/New_York'):%Y-%m-%d %H:%M} New York", default_risk=100, default_account=10000,
                max_position=m.MAX_POSITION, cloud=args.cloud, primary=load_summary("primary"), replication=load_summary("replication"), earlier=EARLIER)
    html = TEMPLATE.read_text(encoding="utf-8").replace("__DATA__", json.dumps(data, default=lambda x: x.item()).replace("</", "<\\/"))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    counts = pd.Series([r["status"] for r in data["rows"]]).value_counts().to_dict()
    short_counts = pd.Series([r["status"] for r in short["rows"]]).value_counts().to_dict()
    print(f"as of {data['as_of']}, market {'green' if data['green'] else 'not green'}, {data['scanned']} scanned, {data['screened']} passed the long screener: {counts}")
    print(f"short side {'on' if short['red'] else 'off'}, {short['screened']} passed the short screener: {short_counts}")
    print(f"wrote {out.resolve()} ({out.stat().st_size / 1e6:.1f} MB)")
    if not args.no_open:
        webbrowser.open(out.resolve().as_uri())


if __name__ == "__main__":
    main()
