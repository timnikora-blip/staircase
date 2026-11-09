# Staircase test â€” short_primary

4309 US common stocks outside the S&P 1500. 267 had candidates and passed the market cap floor, 26 were under it or unknown, 8 had no hourly bars.
2025-03-28 â†’ 2026-11-04, 8 months. Rules: Staircase_Short_Strategy.md.

**Success criteria met: NO**

Signal minus random: +0.208R, 95% CI -0.440 â€¦ +0.948

| Slice | Trades | Win % | Expectancy (net R) | 95% CI (by month) |
|---|---|---|---|---|
| Trades | 46 | 43% | +0.178 | -0.657 â€¦ +1.150 |
| Random entries, same days and stops | 46 | 50% | -0.030 | -0.337 â€¦ +0.310 |
| Without the single best trade | 45 | 42% | +0.030 | -0.672 â€¦ +0.869 |
| Market filter off | 308 | 38% | +0.019 | -0.271 â€¦ +0.352 |
| Cover all on a close above EMA21 | 46 | 28% | -0.100 | -0.906 â€¦ +0.836 |
| Best-case fill at the trigger | 41 | 41% | +0.943 | -0.137 â€¦ +1.798 |
| Closed below the trigger | 38 | 53% | +0.467 | -0.568 â€¦ +1.509 |
| Failed by the close | 8 | 0% | -1.194 | -1.285 â€¦ -1.038 |

Median R -0.74, median risk 4.8% of price, median hold 3 days, same-day stop 11%, best +6.9R, worst -3.1R.

| Exit | Trades | Avg R |
|---|---|---|
| ema_close | 14 | +1.58 |
| open | 6 | +1.85 |
| stop | 26 | -0.97 |

Portfolio: 32 trades, 6% invested on average. Strategy CAGR +4.3%, drawdown 11.0%, Sharpe 0.44. SPY CAGR +20.0%, drawdown 12.1%, Sharpe 1.15.

| Year | Trades | Expectancy | Random |
|---|---|---|---|
| 2025 | 19 | +0.645 | -0.031 |
| 2026 | 27 | -0.150 | -0.029 |
