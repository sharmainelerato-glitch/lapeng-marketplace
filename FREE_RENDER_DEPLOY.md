# LAPENG on Render Free — hackathon preview

## Important: $0 architecture with temporary data
This is a FREE **preview**, not durable marketplace hosting. The Render service uses `plan: free` with **no paid disk**. Render can spin it down after 15 minutes of inactivity. The SQLite database at `/tmp/lapeng-demo.sqlite3`, signed-in sessions, placed demo orders, custom listings, and uploaded product images can disappear after a restart or redeploy. The application itself, built-in CSS/assets and demo-labelled fictional sample listings remain available on new starts. **Never collect real buyer addresses or real payments** here; PayPal Sandbox only.

This release deliberately avoids pretending that setting `DATABASE_URL` alone converts SQLite to PostgreSQL. All backend modules use SQLite-specific SQL. Durable $0 hosting requires a real external database integration and an external image-store integration, followed by full regression tests; neither is included in this quick free preview.

## Install with PowerShell in your GitHub deployment repo folder
1. Back up your existing local working project, if applicable; this package is for your *deployment repository*, not your local database.
2. Download `LAPENG_Render_Free_Demo.zip` to Downloads.
3. Run the provided `INSTALL_FREE_RENDER_WINDOWS.ps1` script **from the root of your GitHub deployment checkout** (the folder containing `render.yaml` and `app/main.py`).
4. Review `git diff --stat`, `git diff render.yaml`, `git status` and `git ls-files` before committing; the script never pushes automatically.
5. Commit and push: `git add render.yaml FREE_RENDER_DEPLOY.md static/index.html static/demo-notice.css` (and changed docs, if present); `git commit -m "Switch LAPENG hackathon preview to Render Free"`; `git push origin main`.
6. In Render Dashboard create **New > Blueprint** from the GitHub repository. **Review plan = Free, disk = none, no paid database**, and do not confirm anything that displays a price. If an old paid Blueprint is already configured, do not deploy it; choose the free service configuration. When Render asks for `APP_BASE_URL`, enter the actual HTTPS origin (such as https://lapeng-free-demo.onrender.com) with no trailing slash. Leave optional Sandbox and AI keys blank until needed, or add them as environment secrets in Render. Never commit secrets.
7. After deployment, check `https://YOUR-SERVICE.onrender.com/health` and test browsing, buyer/provider onboarding, checkout UI, and the AI fallback. Sandbox checkout requires sandbox credentials. Use **fictional test details only**.

## Cost and risk
Render advertises Free web services, but they have monthly usage allowances; bandwidth overage can generate charges depending on account billing setup. Check the current dashboard/billing terms and do not add a payment method or enable paid resources if you require zero possible charges. The repository contains no automatic paid upgrade.

## Future durable upgrade
For persistent accounts, order history and photos, integrate an external free-tier database and object-storage provider with quotas, plus migration and integration tests. This is a separate engineering step and should not be claimed complete in the hackathon demo.
