# Staircase test â€” short_daily

1482 S&P 1500 tickers over 10 years. Entry at the close of the breakdown day, stop at that day's high.
2018-02-08 â†’ 2026-11-04, 37 months. Rules: Staircase_Short_Strategy.md.

**Success criteria met: NO**

Signal minus random: -0.039R, 95% CI -0.336 â€¦ +0.320

| Slice | Trades | Win % | Expectancy (net R) | 95% CI (by month) |
|---|---|---|---|---|
| Trades | 120 | 29% | -0.228 | -0.532 â€¦ +0.127 |
| Random entries, same days and stops | 120 | 33% | -0.189 | -0.283 â€¦ -0.099 |
| Without the single best trade | 119 | 29% | -0.328 | -0.595 â€¦ -0.053 |
| Market filter off | 536 | 34% | -0.218 | -0.355 â€¦ -0.073 |
| Cover all on a close above EMA21 | 120 | 19% | -0.366 | -0.698 â€¦ +0.065 |

Median R -1.02, median risk 5.2% of price, median hold 4 days, same-day stop 0%, best +11.7R, worst -2.4R.

| Exit | Trades | Avg R |
|---|---|---|
| ema_close | 35 | +1.40 |
| open | 4 | +0.90 |
| stop | 81 | -0.99 |

Portfolio: 107 trades, 4% invested on average. Strategy CAGR -1.3%, drawdown 14.5%, Sharpe -0.22. SPY CAGR +14.4%, drawdown 33.7%, Sharpe 0.81.

| Year | Trades | Expectancy | Random |
|---|---|---|---|
| 2018 | 21 | -0.597 | -0.248 |
| 2019 | 7 | -0.411 | -0.178 |
| 2020 | 6 | -0.182 | -0.123 |
| 2021 | 2 | -0.771 | -0.555 |
| 2022 | 34 | -0.185 | -0.140 |
| 2023 | 9 | +0.626 | -0.063 |
| 2024 | 6 | +1.152 | -0.588 |
| 2025 | 19 | -0.572 | -0.264 |
| 2026 | 16 | -0.289 | -0.028 |
