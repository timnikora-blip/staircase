# Staircase Breakdown (short side) — rules and test plan

Source: `ssstik.io_1794016442001.mp4`, supplied by the user, 4:11 long, opening with "My full strategy guide as 7 figure trader". It appears to be the same trader as `Staircase_Strategy.md`.
Rules were read from a local transcript of the audio (`transcripts/staircase_short_video.txt`) and the screen.

Written before seeing any results (2026-11-06). Rules below are frozen for the test.
Numbers marked *(mine)* are not in the video. They had to be chosen to make the rules testable.

## What the video says

| Time | Rule |
|---|---|
| 0:14 | Add the 8, 21 and 50 EMAs |
| 0:35, 1:13 | Below the averages, play the downside. When the market is below them, look to short until it reclaims them |
| 0:45 | Downtrends move in a staircase: leg down, sideways, leg down |
| 1:36 | Screener: price > $3, market cap > $300M, EMA8 above price by 0% to 3%, EMA21 above price, 10-day average volume > 500K, ADR ≥ 3% |
| 2:02 | The stock is below the averages, downtrending, in a tight base |
| 2:12 | Volume is very high on the sell side |
| 2:25 | Trigger: a level respected multiple times, marked at the low |
| 2:47 | Wait for it to take out that spot with volume |
| 2:53 | On the 5 minute chart, short the moment it breaks. "I don't wait for anything else" |
| 3:03 | Stop: high of the day |
| 3:22 | After one or two down days, trim into weakness. Don't cover it all |
| 3:48 | Keep trimming on weakness. Cover the rest on a close above the 8 and 21 EMAs |

Claim made, with no account statement: over $1M this year, from a strategy described as very simple.

## Rules

### 1. Market filter
SPY and QQQ both close below their 8, 21 and 50 EMAs on the prior day *(mine: the video says "below the moving averages")*.

### 2. Screener, on the prior close
Close > $3, 10-day average volume > 500K, 20-day ADR ≥ 3%, EMA8 above the close by 0% to 3%, EMA21 above the close, market cap > $300M.

### 3. Base, ending the day before entry
Base of N = 5…25 days, longest that passes. These mirror the long rules in `Staircase_Strategy.md`:
- **Prior leg down:** the low just before the base is at least max(15%, 5 × ADR) below the highest high of the 40 days before it *(mine)*.
- **Tight:** base range ≤ 3.5 × ADR *(mine)*.
- **Trigger:** the base low, tested at least twice: two non-adjacent days within 0.25 × ADR of it *(mine)*.
- **Below the averages:** base high ≤ EMA50, prior close < EMA21 *(mine)*.
- **Sell-side volume:** mean volume on down days > mean volume on up days, over the base and the 20 days before it *(mine)*.

### 4. Entry and stop
First hourly close below the trigger with cumulative volume ≥ 1.5 × normal pace for that hour *(1.5 is mine)*. Stop is the high of the day so far. Skip if risk is under 0.5% of price *(mine)*.

### 5. Exit
Counted from the day after entry. A down day closes below the prior close and below the entry.
- **First third:** at the close of the 2nd down day *(mine: "one or two down days", and the size isn't stated)*.
- **Second third:** at the close of the 4th down day *(mine)*.
- **Rest:** on a close above both EMA8 and EMA21, at the next open. This applies from day one.
- The stop stays at its original level throughout, since the video doesn't move it. One open trade per ticker.

### 6. Portfolio
At most 5 open positions, highest volume first on the same day, 1% risk per trade, position capped at 20% of equity *(mine)*.

## Test

**Costs:** $0.01/share commission each side, 0.10% slippage on entry, stops, exits and trims. Borrow at 3% a year of entry value *(mine)*. Many small, falling stocks cost far more to borrow, or can't be borrowed at all.

**Control:** for each trade, 20 random short entries in the same ticker, at the close on days that pass the market filter and screener but need no base or breakdown, with the same stop width in ATR and the same exits.

### Two tests, because each misses something
- **A, closest to the video:** US common stocks outside the S&P 1500, about 2 years, 1h entries.
- **B, covers more bear markets:** S&P 1500, 10 years, entry at the close of a breakdown day on ≥ 1.5 × volume, stop at that day's high. Those tickers were used for long rules, but no short rule has been tested on them.

Both run once. No tuning. A small sample may be run first only to check the code for bugs, printing individual trades and no totals.

### Verdict
Each test is judged on: (1) net expectancy with 95% CI lower bound > 0, and (2) signal minus control with 95% CI lower bound > 0. CIs are bootstrapped by calendar month.

A test with **under 12 months containing trades can't carry a verdict** and is reported as too thin, because the market filter is rarely on. An edge is proven only if every test with enough months passes both conditions. Anything less means no proven edge.

### Known limits
- **Survivorship works against shorts here.** Stocks that collapsed and delisted are missing, which removes some of the best shorts. The control shares this. Don't read a weak result as stronger evidence than it is.
- **Market cap is today's**, which favours stocks that have held up. This also works against shorts.
- **Dividends aren't charged.** Prices are split-adjusted only, so a short gets credit for ex-dividend drops and doesn't pay the dividend. This flatters shorts slightly.
- **Availability isn't modelled:** hard-to-borrow stocks, recalls, short-sale restrictions after a 10% drop, and squeezes beyond what daily gaps show.
- **1h is not 5m.** Entries are later and stops wider than the video's.
- Few bear-market periods exist, even in 10 years, so results lean on a handful of episodes.

### Reported, not part of the verdict
- Market filter off.
- Fill at the trigger on the first bar through it, a best case that uses the whole hour's high and volume.
- Cover everything on the first close above EMA21.
- Results without the single best trade.
- Trades that closed below the trigger vs those that failed the same day.
- Portfolio return and drawdown vs SPY.
