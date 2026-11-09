"""Whole-market watchlist with charts for the momentum breakout strategy: writes momentum_dashboard.html.

Usage (from the trading folder), each morning before the open:
    .venv\\Scripts\\python -m backtest.momentum_dashboard
    .venv\\Scripts\\python -m backtest.momentum_dashboard --no-refresh     # reuse the last download

Scans every US-listed common stock, not just the S&P 1500 used in the backtest (Momentum_Strategy.md).
The rule count measures how well a stock matches the strategy's rules. It is NOT a probability of
winning: the strategy failed its holdout test (results/momentum/), and smaller stocks weren't tested at all.
"""
import argparse
import io
import json
import logging
import urllib.request
import warnings
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from . import momentum as m

TEMPLATE = Path(__file__).with_name("momentum_dashboard_template.html")
MARKET_DIR = Path("data/us_all")
SYMBOL_FILES = ("https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt",
                "https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt")
NOT_COMMON = r"(?i)warrant|\bunits?\b|\brights?\b|preferred|\bnotes?\b|debenture|\d%"
HISTORY = "2y"
MIN_BARS = m.BASE_MAX + m.POLE_LOOKBACK + 5
MIN_MARKET_CAP = 300e6
CHART_BARS = 120
PIN_JUMP_DAYS = 30
PIN_MIN_JUMP = 0.25
PIN_MAX_RANGE = 0.01
RULES = dict(
    pole=f"Prior move of at least {m.POLE_MIN_GAIN:.0%} or {m.POLE_ADR_MULT:.0f}× ADR",
    range=f"Base range within {m.BASE_RANGE_ADR}× ADR",
    tail=f"Last 5 days tight, average range under {m.TAIL_RANGE_ADR}× ADR",
    volume="Volume lower in the base than before it",
    above_e50="Base low holds above EMA50",
    above_e21="Close above EMA21",
    touches="Trigger level tested at least twice",
    early="First or second breakout of this trend",
)


def _p(x):
    return f"{x:,.2f}"


# ---------------------------------------------------------------- whole-market data

def fetch_symbols():
    """Every US-listed common stock from the Nasdaq Trader symbol files, without ETFs and test issues."""
    frames = []
    for url in SYMBOL_FILES:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        text = urllib.request.urlopen(req, timeout=30).read().decode("utf-8")
        df = pd.read_csv(io.StringIO(text), sep="|", dtype=str, keep_default_na=False)
        frames.append(df.rename(columns={"ACT Symbol": "Symbol"})[["Symbol", "Security Name", "ETF", "Test Issue"]])
    df = pd.concat(frames)
    df = df[(df["ETF"] == "N") & (df["Test Issue"] == "N") & ~df["Symbol"].str.contains(r"\$")]
    df = df[~df["Security Name"].str.contains(NOT_COMMON)]
    return pd.DataFrame({"ticker": df["Symbol"].str.replace(".", "-", regex=False),
                         "name": df["Security Name"].str.split(" - ").str[0]}).drop_duplicates("ticker").sort_values("ticker")


def _download(tickers, chunk=200):
    """Daily bars per ticker, in batches. Tickers Yahoo doesn't return are simply left out."""
    import yfinance as yf

    out = {}
    cutoff = m.first_unfinished_day()
    for start in range(0, len(tickers), chunk):
        batch = tickers[start:start + chunk]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            raw = yf.download(batch, period=HISTORY, interval="1d", auto_adjust=False, group_by="ticker",
                              progress=False, threads=True)
        for t in batch:
            if t in raw.columns.get_level_values(0):
                df = raw[t].copy()
                df.columns = [c.lower() for c in df.columns]
                df = df[["open", "high", "low", "close", "volume"]].dropna()
                df = df[df.index < cutoff]
                if len(df) >= MIN_BARS:
                    out[t] = df
        print(f"{min(start + chunk, len(tickers))}/{len(tickers)} requested, {len(out)} with enough history", flush=True)
    return out


def fetch_market():
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    symbols = fetch_symbols()
    MARKET_DIR.mkdir(parents=True, exist_ok=True)
    symbols.to_csv(MARKET_DIR / "universe.csv", index=False)
    print(f"universe: {len(symbols)} US common stocks")
    frames = _download(list(m.MARKET) + symbols["ticker"].tolist())
    calendar = frames["SPY"].index
    bars = {f: pd.DataFrame({t: df[f].reindex(calendar) for t, df in frames.items()})
            for f in ("open", "high", "low", "close", "volume")}
    pd.to_pickle(bars, MARKET_DIR / "bars.pkl.gz", compression={"method": "gzip", "compresslevel": 1})
    (MARKET_DIR / "market_caps.csv").unlink(missing_ok=True)


def _market_cap(ticker):
    import yfinance as yf

    try:
        return float(yf.Ticker(ticker).fast_info["marketCap"])
    except Exception:
        return np.nan


def market_caps(tickers):
    """Current market caps, cached until the next refresh. Unknown ones are NaN and stay in the list."""
    path = MARKET_DIR / "market_caps.csv"
    known = pd.read_csv(path, index_col=0)["market_cap"].to_dict() if path.exists() else {}
    missing = [t for t in tickers if t not in known]
    if missing:
        print(f"looking up {len(missing)} market caps", flush=True)
        with ThreadPoolExecutor(8) as pool:
            known.update(zip(missing, pool.map(_market_cap, missing)))
        pd.Series(known, name="market_cap").rename_axis("ticker").to_csv(path)
    return known


# ---------------------------------------------------------------- scan

def best_base(s, i):
    """The base length passing the most rules, longest first on ties (as find_base prefers)."""
    best = None
    for n in range(m.BASE_MAX, m.BASE_MIN - 1, -1):
        checks, hi, lo = m.base_checks(s, i, n)
        if best is None or sum(checks.values()) > sum(best[1].values()):
            best = (n, checks, hi, lo)
    return best


def breakouts_so_far(s):
    """Breakouts already in this trend, counting the last close, as seen by the next session."""
    last = len(s.c) - 1
    return int(m._mark_prior_breakouts(s)[last] + m.is_raw_breakout(s, last))


def looks_pinned(s):
    """A huge one-day jump, then almost no movement: usually a takeover target sitting near its deal price.
    Such stocks pass the tightness rules for the wrong reason. Page warning only; not part of the backtested rules."""
    jump = np.nanmax(s.c[-PIN_JUMP_DAYS:] / s.c[-PIN_JUMP_DAYS - 1:-1] - 1)
    recent_range = np.nanmean((s.h[-5:] - s.l[-5:]) / s.c[-5:])
    return bool(jump >= PIN_MIN_JUMP and recent_range <= PIN_MAX_RANGE)


def notes_for(row, green):
    t, u, a = row["trigger"], row["undercut"], row["atr"]
    notes = []
    if row["pinned"]:
        notes.append(f"Possible takeover: it jumped at least {PIN_MIN_JUMP:.0%} in one day within the last {PIN_JUMP_DAYS} sessions and has barely moved since. "
                     "Check the news first. A stock held near a deal price isn't a coiled base, and little upside may be left.")
    if not green:
        notes.append("NO NEW TRADE while the market filter is off: SPY and QQQ must both close above their 8, 21 and 50 EMAs.")
    if row["missing"]:
        notes.append("Not a setup yet. Missing: " + "; ".join(row["missing"]) + ". Levels below are the nearest base and will move.")
    notes += [
        f"Breakout: set an alert at {_p(t)}. Enter when it clears that level with volume running at least "
        f"{m.BREAKOUT_RVOL}× normal, which is about {row['breakout_volume']:,} shares for a full day. "
        "Skip it if the stock isn't up on the day.",
        f"Undercut: if it trades below {_p(u)} and closes back above it, without closing above {_p(t)}, enter on the reclaim. "
        "It must also be up on the day and above EMA21 and EMA50. No volume condition.",
        f"Stop: low of the day at entry. Skip the trade if that is more than {_p(m.MAX_STOP_ATR * a)} from your entry ({m.MAX_STOP_ATR} ATR). "
        "Exact shares = risk ÷ (entry − low of day), capped at 20% of your account.",
        f"First trim: sell a quarter at +{m.TARGET_R:.0f}R, then move the stop to breakeven.",
        f"After the first trim: sell a quarter on a close below EMA8 (now {_p(row['e8'])}) and another on a close below EMA21 (now {_p(row['e21'])}), each at the next open.",
        f"Sell everything on a close below EMA50 (now {_p(row['e50'])}), at the next open. This applies from day one.",
        "The rules don't cover earnings, so check the date before holding through one. Log the trade whether you take it or not.",
    ]
    return notes


def _rounded(a):
    return [None if np.isnan(x) else round(float(x), 2) for x in a[-CHART_BARS:]]


def chart_data(s):
    return dict(o=_rounded(s.o), h=_rounded(s.h), l=_rounded(s.l), c=_rounded(s.c),
                v=[None if np.isnan(x) else int(x) for x in s.v[-CHART_BARS:]],
                e8=_rounded(s.e8), e21=_rounded(s.e21), e50=_rounded(s.e50))


def build(bars):
    names = pd.read_csv(MARKET_DIR / "universe.csv", keep_default_na=False).set_index("ticker")["name"].to_dict()
    green, rs = m.market_green(bars), m.rs_top(bars)
    rank = m.rs_rank(bars).iloc[-1]
    passed_scan = {}
    for t in rs.columns[rs.iloc[-1].to_numpy()]:  # relative strength first: it removes 80% of tickers cheaply
        s = m.Series(t, bars, green, rs)
        i = len(s.c)
        p = i - 1
        if (np.isfinite(s.c[p] + s.atr[p]) and s.c[p] > m.MIN_PRICE and s.v[p] > m.MIN_VOLUME and s.adr20[p] >= m.MIN_ADR
                and s.c[p] > s.e8[p] and s.c[p] > s.e21[p] and s.c[p] > s.e50[p]
                and i >= MIN_BARS and not np.isnan(s.l[i - m.BASE_MAX - m.POLE_LOOKBACK])):
            passed_scan[t] = s
    caps = market_caps(list(passed_scan))
    rows = []
    for t, s in passed_scan.items():
        cap = caps.get(t, np.nan)
        if cap < MIN_MARKET_CAP:
            continue
        i = len(s.c)
        p = i - 1
        n, checks, hi, lo = best_base(s, i)
        checks = dict(checks, early=breakouts_so_far(s) <= m.MAX_PRIOR_BREAKOUTS)
        missing = [RULES[k] for k, ok in checks.items() if not ok]
        row = dict(ticker=t, name=names.get(t, ""), market_cap=None if np.isnan(cap) else cap,
                   close=s.c[p], trigger=hi, undercut=lo, to_trigger=hi / s.c[p] - 1, base_days=n,
                   atr=s.atr[p], adr=s.adr20[p], rs=float(rank[t]), avg_volume=int(s.vol20[p]),
                   breakout_volume=int(m.BREAKOUT_RVOL * s.vol20[p]), e8=s.e8[p], e21=s.e21[p], e50=s.e50[p],
                   passed=sum(checks.values()), total=len(checks), missing=missing,
                   checks=[[RULES[k], bool(ok)] for k, ok in checks.items()], chart=chart_data(s))
        row["pinned"] = looks_pinned(s)
        row["status"] = ("Possibly pinned" if row["pinned"] else "Ready" if not missing
                         else "One rule short" if len(missing) == 1 else "Forming")
        row["notes"] = notes_for(row, bool(green.iloc[-1]))
        rows.append(row)
    rows.sort(key=lambda r: (r["pinned"], -r["passed"], -r["avg_volume"]))
    market = []
    for t in m.MARKET:
        c = bars["close"][t]
        market.append(dict(ticker=t, close=float(c.iloc[-1]),
                           emas=[[f"EMA{w}", float(m.ema(c, w).iloc[-1])] for w in (8, 21, 50)]))
    calendar = bars["close"].index
    return dict(generated=f"{pd.Timestamp.now(tz='America/New_York'):%Y-%m-%d %H:%M} New York",
                as_of=f"{calendar[-1]:%Y-%m-%d}", green=bool(green.iloc[-1]), market=market,
                scanned=bars["close"].shape[1] - len(m.MARKET), dates=[f"{d:%Y-%m-%d}" for d in calendar[-CHART_BARS:]],
                default_risk=100, default_account=10000, max_position=m.MAX_POSITION, rows=rows)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--no-refresh", action="store_true", help="use the last download (a refresh takes several minutes)")
    p.add_argument("--out", default="momentum_dashboard.html")
    p.add_argument("--no-open", action="store_true", help="don't open the page in the browser")
    args = p.parse_args()

    if not args.no_refresh:
        fetch_market()
    data = build(pd.read_pickle(MARKET_DIR / "bars.pkl.gz"))
    html = TEMPLATE.read_text(encoding="utf-8").replace("__DATA__", json.dumps(data, default=lambda x: x.item()).replace("</", "<\\/"))
    out = Path(args.out)
    out.write_text(html, encoding="utf-8")
    counts = pd.Series([r["status"] for r in data["rows"]]).value_counts().to_dict()
    print(f"as of {data['as_of']}, market {'green' if data['green'] else 'not green'}, "
          f"{data['scanned']} stocks scanned, {len(data['rows'])} leaders: {counts}")
    print(f"wrote {out.resolve()} ({out.stat().st_size / 1e6:.1f} MB)")
    if not args.no_open:
        webbrowser.open(out.resolve().as_uri())


if __name__ == "__main__":
    main()
