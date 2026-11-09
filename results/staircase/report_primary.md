# Staircase test — primary

4309 US common stocks outside the S&P 1500. 965 had candidates and passed the market cap floor, 275 were under it or unknown, 43 had no hourly bars.
2025-02-21 → 2026-10-29, 18 months. Rules: Staircase_Strategy.md.

**Success criteria met: NO**

Signal minus random: -0.096R, 95% CI -0.308 … +0.126

| Slice | Trades | Win % | Expectancy (net R) | 95% CI (by month) |
|---|---|---|---|---|
| Trades | 1058 | 26% | +0.121 | -0.104 … +0.336 |
| Random entries, same days and stops | 1058 | 48% | +0.217 | +0.135 … +0.296 |
| Without the single best trade | 1057 | 26% | +0.061 | -0.141 … +0.256 |
| Exit all on a close below EMA21 | 1058 | 20% | +0.073 | -0.175 … +0.338 |
| Best-case fill at the trigger | 975 | 36% | +1.152 | +0.653 … +1.727 |
| Closed above the trigger | 854 | 30% | +0.353 | +0.081 … +0.603 |
| Failed by the close | 204 | 7% | -0.850 | -0.991 … -0.714 |

Median R -1.02, median risk 4.2% of price, median hold 4 days, same-day stop 14%, best +63.3R, worst -7.8R.

| Exit | Trades | Avg R |
|---|---|---|
| breakeven | 138 | +1.03 |
| ema50 | 160 | +4.98 |
| open | 5 | +5.40 |
| stop | 755 | -1.11 |

Portfolio: 115 trades, 47% invested on average. Strategy CAGR +19.1%, drawdown 23.6%, Sharpe 0.74. SPY CAGR +13.8%, drawdown 17.0%, Sharpe 0.83.

| Year | Trades | Expectancy | Random |
|---|---|---|---|
| 2025 | 596 | +0.311 | +0.285 |
| 2026 | 462 | -0.124 | +0.130 |
