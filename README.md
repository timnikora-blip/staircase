# Staircase dashboard

A watchlist and playbook for the staircase breakout (long) and breakdown (short) strategies, with their backtests. It scans every US-listed common stock from daily bars.

**Read this first:** neither side showed a proven edge in testing. The long side lost to random entries in the same stocks, and the short side averaged −0.23R per trade over 10 years. Use the page for paper trading, not as a reason to risk money. Details are on the page and in `results/staircase/`.

## On your phone (GitHub, runs in the cloud)
The workflow in `.github/workflows/dashboard.yml` builds the page on GitHub's servers, even with your PC off. It runs twice each weekday: in the evening after the close, and before the open, by which time Yahoo has filled in the previous session.

**One-time setup (about 10 minutes, all in a browser):**
1. Sign in at github.com, with the same account as the Gerchik `levels` repository if you like.
2. Click **+** (top right) → **New repository**. Name it, e.g. `staircase`, and choose **Public** (free GitHub Pages needs a public repository). Click **Create repository**.
3. On the new repo page, click **uploading an existing file**. Open the folder `trading\github_upload`, select **everything inside it**, including the `.github` folder, and drag it onto the page. Click **Commit changes**.
4. Check that the file list shows `.github`. If it doesn't, click **Add file → Create new file**, type `.github/workflows/dashboard.yml` as the name, paste in the contents of that file, and commit.
5. Go to **Settings → Pages**. Under "Build and deployment" → Source, choose **GitHub Actions**.
6. Go to the **Actions** tab. If asked, click to enable workflows. Then click **Dashboard** → **Run workflow** → **Run workflow**. The first run takes about 10–15 minutes, because it downloads two years of bars for about 5,800 stocks.
7. Your dashboard is at `https://YOUR-USERNAME.github.io/staircase/`. In Safari: Share → **Add to Home Screen**.

**Notes:**
- The page is public, but only someone with the link finds it. It shows setups and test results, nothing personal. The strategy code in the repository is public too.
- Your risk settings, pinned charts and chosen tab are saved on each device separately.
- For a fresh run, use the GitHub app: repo → Actions → Dashboard → Run workflow.
- If Yahoo blocks or slows GitHub's servers, a run fails and the page keeps the last good version. The PC version keeps working either way.
- When the code changes on your PC, upload the changed files again (step 3 replaces files with the same name).

## On your PC
From the `trading` folder:

```
.venv\Scripts\python -m backtest.staircase_dashboard
```

Rules and test plans: `Staircase_Strategy.md` and `Staircase_Short_Strategy.md`.
