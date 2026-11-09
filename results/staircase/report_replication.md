# Staircase test — replication

1482 S&P 1500 tickers, used in earlier tests, so this is supporting evidence only. Entry at the daily close. No market cap filter is needed for index members.
2017-02-17 → 2026-10-29, 105 months. Rules: Staircase_Strategy.md.

**Success criteria met: NO**

Signal minus random: +0.049R, 95% CI -0.209 … +0.417

| Slice | Trades | Win % | Expectancy (net R) | 95% CI (by month) |
|---|---|---|---|---|
| Trades | 2369 | 27% | +0.094 | -0.172 … +0.476 |
| Random entries, same days and stops | 2369 | 47% | +0.045 | +0.013 … +0.078 |
| Without the single best trade | 2368 | 27% | -0.015 | -0.178 … +0.150 |
| Exit all on a close below EMA21 | 2369 | 24% | -0.044 | -0.235 … +0.163 |

Median R -1.02, median risk 3.7% of price, median hold 6 days, same-day stop 0%, best +256.9R, worst -23.7R.

| Exit | Trades | Avg R |
|---|---|---|
| breakeven | 242 | +1.11 |
| ema50 | 515 | +3.59 |
| open | 8 | +2.22 |
| stop | 1604 | -1.19 |

Portfolio: 446 trades, 46% invested on average. Strategy CAGR -1.0%, drawdown 28.0%, Sharpe -0.01. SPY CAGR +14.2%, drawdown 33.7%, Sharpe 0.82.

| Year | Trades | Expectancy | Random |
|---|---|---|---|
| 2017 | 116 | -0.072 | +0.111 |
| 2018 | 112 | -0.082 | +0.030 |
| 2019 | 214 | -0.076 | +0.099 |
| 2020 | 378 | +0.264 | +0.016 |
| 2021 | 333 | -0.223 | -0.020 |
| 2022 | 82 | -0.599 | -0.037 |
| 2023 | 312 | -0.297 | +0.064 |
| 2024 | 279 | -0.149 | +0.043 |
| 2025 | 313 | +1.176 | +0.123 |
| 2026 | 230 | +0.200 | +0.005 |
