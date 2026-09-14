# bar-sales-bridge

Pulls Square sales for **Tique's, Paddle Bar and Volstead** on GitHub's servers
(which can reach Square) and commits the numbers here as JSON, so Ryan's Claude
tasks can read them without calling Square directly.

## Files Claude reads

| File | What it holds |
|---|---|
| `wrap.json` | **The most recent night.** Before 4 AM ET it's the day in progress; after 4 AM ET it's yesterday's full day with `"is_final": true`. The 1 AM nightly wrap reads this. |
| `days/YYYY-MM-DD.json` | One file per business day (4 AM ET → 4 AM ET). Yesterday's is re-pulled and finalized on every run, so a late run can't wipe last night. |
| `paddle_volstead.json` | The day in progress. Old name, kept for compatibility. |

Each file: `generated_at_et`, `business_day`, `is_final`, `errors`, `combined`
(net sales / transactions / tips / open tabs across all three), and `bars`
keyed `tiques` / `paddle` / `volstead` with net sales, tax back-out, counts,
tips, cash vs card, discounts, line items by category, custom amounts.

Business day rolls at **4:00 AM Eastern**.

## How it runs

1. **Mac mini trigger (primary).** `mac/install.sh` sets up macOS launchd jobs
   on the always-on Mac mini that poke GitHub at exact times (every 30 min
   from 4:05 PM to 12:35 AM, plus 12:50 AM). Those runs start immediately.
2. **GitHub schedule (backup only).** GitHub delays or skips scheduled runs on
   free repos when busy — we saw 3–4 runs a day instead of every 30 minutes —
   so the crons in `.github/workflows/pull-sales.yml` are just a safety net.

Secrets (Actions → Secrets): `SQUARE_TIQUES_TOKEN`, `SQUARE_PADDLE_TOKEN`,
`SQUARE_VOLSTEAD_TOKEN`. Tokens are never written to the repo or logs.

## Reading from a Claude task

`WebFetch` needs a site approval that nobody can click in an unattended run.
Use the shell instead — `github.com` is reachable from the sandbox:

```bash
git clone --depth 1 https://github.com/Riv419/bar-sales-bridge.git /tmp/bsb && cat /tmp/bsb/wrap.json
```

Lodging numbers for The Cedar come from the sister repo `cedar-pricing-bridge`
(`data/lodging/latest.json`).
