# Staircase Breakout (SRxTrades video) — rules and test plan

Source: "The strategy that made me 7 figures in 1 month", @SRxTrades on X, 30 May 2026, 4:25 long.
https://x.com/SRxTrades/status/2060843695918682320

Written before seeing any results (2026-11-06). Rules below are frozen for the test.
Rules were read from the video's burned-in captions and screen, not from its audio. The author also offers a PDF guide, which was not read.
Numbers marked *(mine)* are not in the video. They had to be chosen to make the rules testable.

## What the video says

| Time | Rule |
|---|---|
| 0:30 | Add the 8, 21 and 50 EMAs to the chart |
| 0:30–1:20 | Check QQQ or SPY. Trade the long side when they trend up. Avoid longs and play downside when they trend down |
| 1:20–1:30 | The market moves in a staircase: move up, sideways base, move up. Trade the breakout into the next leg |
| 1:30–2:00 | TradingView screener: price > $3, market cap > $300M, EMA21 and EMA50 below price, average volume (10 day) > 500K, ADR ≥ 2%, sorted by volume |
| 2:00–2:20 | Scroll the list for stocks that went up and are now building a base |
| 2:20–2:50 | Trigger: a level that rejected the stock multiple times. Don't buy inside the base |
| 3:10–3:30 | Entry: on the 5 minute chart, buy right as it gets through the level, with high volume confirming |
| 3:30–3:40 | Stop: low of the day. If stopped, re-enter if it gets back above, or move on |
| 3:40–4:00 | Swing it, and don't sell everything on the same day |

Claims made, none of them evidenced by an account statement: 7 figures in 1 month, $500,000+ on one trade, a trade at 45R. The 45R is open profit on a position-tool drawing with a stop of about 1%.

## How this differs from Momentum_Strategy.md, which already failed its test

Dropped because the video doesn't state them: top 20% relative strength, volume drying up in the base, tight last 5 days, first or second breakout only, the 1.5 ATR limit on the stop, the undercut entry.

Kept from the earlier test, so the two results compare: market filter, prior move, base range, trigger tested twice, costs, and the exits.

## Rules

### 1. Market filter
SPY and QQQ both close above their 8, 21 and 50 EMAs on the prior day *(mine: the video shows the averages but gives no exact test)*. Shorts in a down market are not tested.

### 2. Screener, on the prior close
Close > $3, 10-day average volume > 500K, 20-day ADR ≥ 2%, close above EMA21 and EMA50, market cap > $300M.

### 3. Base, ending the day before entry
Base of N = 5…25 days, longest that passes:
- **Prior move:** the high just before the base is at least max(15%, 5 × ADR) above the lowest low of the 40 days before it *(mine)*.
- **Sideways:** base range ≤ 3.5 × ADR *(mine)*.
- **Trigger:** the base high, tested at least twice: two non-adjacent days within 0.25 × ADR of it *(mine)*.
- **Above the averages:** base low ≥ EMA50, prior close > EMA21 *(mine)*.

### 4. Entry and stop
First hourly close above the trigger with cumulative volume ≥ 1.5 × normal pace for that hour *(1.5 is mine)*. Stop is the low of the day so far. Skip if risk is under 0.5% of price, because hourly bars can't resolve a tighter stop *(mine)*.

The video uses 5 minute bars. Yahoo keeps those for 60 days only, so 1h is the closest testable version.

A stopped trade may trigger again on a later day if a base still passes. Same-day re-entry is not modelled.

### 5. Exit
The video gives none beyond "don't sell it all the same day". The test uses the same quarters as Momentum_Strategy.md *(mine)*: a quarter at +3R then stop to breakeven, a quarter on a close below EMA8, a quarter on a close below EMA21, the rest on a close below EMA50, each at the next open. The stop stays live. One open trade per ticker.

### 6. Portfolio
At most 5 open positions, highest volume first on the same day, 1% risk per trade, position capped at 20% of equity *(mine)*.

## Test

**Costs:** $0.01/share commission each side, 0.10% slippage on entry, stops and next-open exits. No slippage on the limit trim at +3R.

**Control:** for each trade, 20 random entries in the same ticker, at the close on days that pass the market filter and screener but need no base or breakout, with the same stop width in ATR and the same exits.

### Primary test, run once
US common stocks **outside the S&P 1500**, about 2 years. These tickers have never been part of a test of this kind, and they match the video's screener, which isn't limited to index members. No tuning and no dev split: the rules are frozen, and the single run is the result.

A small sample of already-used S&P 1500 tickers may be run first, only to check the code for bugs. It can't change a rule.

### Verdict, judged on the primary test
1. Net expectancy > 0, with 95% CI lower bound > 0, **and**
2. Signal minus control > 0, with 95% CI lower bound > 0.

CIs are bootstrapped by calendar month. Anything less than both conditions means no proven edge.

### Known limits
- **Survivorship:** only stocks still listed today, which flatters long momentum. The control shares it, so the comparison is the fairer number.
- **Market cap is today's**, not the cap at the time. A stock that grew past $300M counts all along, one that fell below it doesn't count at all. This flatters results further. The control shares it too.
- **Two years is short**, and mostly one market regime, so the CI will be wide and won't capture regime risk.
- **1h is not 5m.** Entries are later and stops wider than the video's.

### Reported, not part of the verdict
- Fill at the trigger on the first bar through it, rather than at the hourly close. This is a best case, since it ignores the order of the high and low within the bar.
- Exit everything on a close below EMA21.
- Results without the single best trade.
- Trades that closed above the trigger vs those that failed the same day.
- Portfolio return and drawdown vs SPY.
- Replication on S&P 1500 tickers over 10 years, entered at the daily close. Those tickers were used before, so this is supporting evidence only.
