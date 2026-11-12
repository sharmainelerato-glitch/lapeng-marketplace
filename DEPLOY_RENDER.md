# LAPENG — Render hackathon MVP deployment

## What is included

- Existing FastAPI backend, buyer/provider marketplace, checkout, AI navigation cleanup.
- `render.yaml` for a **single paid Starter** web service and a **1 GB persistent disk**.
- SQLite (`/var/data/lapeng.sqlite3`) and uploaded photos (`/var/data/uploads`).
- PayPal **Sandbox only**. No live seller payouts, no automatic migration to PostgreSQL.
- Seeded fictional demo providers **disabled** on a fresh deployment. Create your own clearly labelled test accounts/listings for the video.

## Before deployment

1. Keep `.env`, `lapeng.sqlite3`, `uploads/`, all backups and test user data out of your GitHub repository. See `.gitignore`.
2. From this package run `python -m pip install -r requirements.txt` and `python -m pytest tests/test_release_address.py -q`. A broader full suite might still have legacy failures; resolve them before claiming production readiness.
3. Open GitHub and create a **new private repository first**. Push the clean source from this folder only (never the old local project folder, because it may contain secrets or historical database files in git history). Make it public only after reviewing the repository and competition rules.
4. In Render, create a new Blueprint and connect that GitHub repository (`render.yaml`). A paid Starter web service with attached disk will incur charges. Confirm cost before applying. **Do not choose the free web service for this SQLite plan:** it cannot attach persistent disks.
5. At first Blueprint creation, supply `APP_BASE_URL` (exact HTTPS origin such as `https://lapeng-demo.onrender.com`, no ending slash). You may leave optional Sandbox and AI keys blank until ready. Configure their secrets in the Render dashboard if Blueprint has already been created.
6. Once running, visit `https://YOUR-SERVICE.onrender.com/health`, then browse, register test users, switch Buyer and Provider, create listings, test enquiries and saved addresses. Do a PayPal Sandbox transaction only with Sandbox test accounts and keys.
7. Verify uploaded images and an account **survive a redeploy**, confirm login and order isolation with multiple test users, and open the app on phone and desktop.
8. Do **not** copy your local SQLite database to a public hosted instance if it contains personal records. For a demo, start fresh and create consensual, labelled test data.

## PostgreSQL / Supabase

Not needed for this specific MVP. The app uses SQLite connections and SQLite-specific SQL throughout. Setting `DATABASE_URL` to PostgreSQL or Supabase will **not** migrate the app. A real migration requires rewriting storage access, verifying migrations, testing transactions and photo storage separately.

## Important limitations

The persistent disk is single-instance oriented and not a managed database backup solution. Arrange backups before storing real data. The application is a **hackathon demonstration**, not validated for real purchases or production security. There is no live PayPal payout system. Do not collect real customer addresses during public judging.

## Local PowerShell checks

Open PowerShell inside the extracted `LAPENG_Render_MVP_Deployment` folder, then run `./CHECK_DEPLOY_WINDOWS.ps1`. This performs basic syntax/package safety checks; it does not deploy to Render or guarantee that full tests pass.
