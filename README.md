# LAPENG — Human-centred Agentic Commerce

**Find what you need. Discover who can help. Grow together.**

LAPENG is a community-first, global-by-design marketplace for independent products, skilled trades and remote services. Its agentic **Opportunity Assembly** function compares actual database listings and capacity constraints, proposes temporary business coalitions, and explains trade-offs through an optional real language-model connection. The **LAPENG Guardian** module provides evidence-based reporting and rules-backed safety screening. One account can switch between Buyer and Provider workspaces.

> **Prototype honesty:** The included provider cards and review counts are *illustrative seeded data*, not verified businesses. No sandbox transaction is ever marked paid without a successful PayPal server-side capture. No claim of escrow or multi-merchant settlement. An AI model is connected only once you supply `AI_API_KEY`; the deterministic matching engine works independently and labels itself accordingly.

## Quick start (Windows PowerShell, uv)

```powershell
# Extract ZIP and open this directory in PowerShell
Copy-Item .env.example .env
# Edit .env with your own credentials; never commit it
uv venv
uv pip install -r requirements.txt
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000**. You can also use `python -m pip install -r requirements.txt` then `python -m uvicorn app.main:app --reload`.

## Demo walk-through

1. Visit the landing page, search for **carpentry**, **web development** or **cake**, and view illustrative profiles.
2. Create a Buyer account. Post a new request such as **Build cabinets for my apartment**, 3 units, city **Johannesburg**, budget **$700** (sample USD values).
3. Open the request and select **Assemble opportunity**. It calculates real matches from the SQLite provider table, capacity allocations and costs, then displays a rules-only or real AI-supported explanation.
4. Open a private browser window and register another user. Switch to Provider, create a profile with a matching category, capacity and pricing, then open the buyer's request from Opportunities and submit a quotation.
5. Back as Buyer, accept the quote. Messaging becomes available to the buyer and participating provider; other users cannot inspect messages.
6. With **PayPal Sandbox credentials** configured, click **Pay with PayPal Sandbox** on the accepted proposal, approve using a **sandbox personal account**, and return to the app. The backend captures and verifies payment value and currency before recording `COMPLETED`. Without credentials, the button reports the configuration gap; it does **not** simulate a paid transaction.
7. Browse Guardian, submit a report, or demonstrate that a verified-payment review cannot be created without a completed capture.

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `APP_BASE_URL` | PayPal redirect | Exact local or HTTPS deployment origin, including port |
| `APP_SECRET` | Before public deployment | Random secret reserved for hardening |
| `PAYPAL_CLIENT_ID` | For payment demo | PayPal Sandbox REST API client ID |
| `PAYPAL_CLIENT_SECRET` | For payment demo | PayPal Sandbox REST API secret; backend-only |
| `AI_API_KEY` | For genuine AI demo | Key for OpenAI-compatible chat completion service |
| `AI_BASE_URL` | If using nondefault LLM | API service base, e.g. `https://api.openai.com/v1` |
| `AI_MODEL` | With AI key | Model identifier accepted by the service |
| `LAPENG_DB` | Optional | SQLite path |

The app uses an OpenAI-compatible `/chat/completions` protocol. LLM output provides grounded explanations; capacity and price decisions remain deterministic.

**PayPal Sandbox setup:** Create a REST application at https://developer.paypal.com/dashboard/applications/sandbox and populate the credentials in `.env`. Use sandbox personal test buyer accounts from https://developer.paypal.com/dashboard/accounts. Match `APP_BASE_URL` to your actual running origin. No PayPal partner approval is assumed for multi-seller settlement. Buyer must accept a quote and explicitly approve on PayPal's hosted checkout. Localhost browser redirects are supported; secure HTTPS is required for internet deployment.

## Feature map

- Public landing, search, provider details, About, Trust and Safety, Privacy, Terms, favicon
- Buyer/Provider unified account; signup/login; role-specific dashboards; provider creation
- Local and remote search; service listings; customer requests; provider quotes; buyer approval
- Request-bound collaboration chat; private messages; project events
- Opportunity Assembly — category/skill relevance, location/remote constraints, stock/capacity constraints, cost and budget; optional AI explanations
- Guardian — report submission, buyer/provider isolation, cautious message warning checks, reviews gated by completed payments
- PayPal Orders v2 sandbox — OAuth, create order, hosted buyer approval, capture, amount/currency verification, duplicate-capture guard, status retrieval
- Responsive layouts and keyboard-friendly controls; original SVG browser favicon

## Critical production gaps (deliberately disclosed)

This hackathon MVP is **not a production marketplace**. Before deployment to actual users, implement email verification, password reset, secure cookies and CSRF policy, authentication rate-limiting and account lockout, a robust managed database, object storage and upload malware scanning, moderation operations and appeal handling, authorized payments onboarding in each country, privacy/consumer laws review, localization, real portfolio and delivery evidence checks, webhook verification and replay/idempotency handling where used, customer/provider identity validation through a qualified vendor, monitoring, anti-bot controls, fraud modeling and accessibility testing. The Terms and Privacy pages are demo summaries, **not legally reviewed policies**.

**No webhook receiver is advertised as implemented**: status verification is currently performed through PayPal's authenticated Orders APIs. This is a conscious choice to avoid claims of unsigned/untested webhook protection.

## Testing

```powershell
uv run pytest -q
```

Tests cover signup, session permissions, provider/quote ownership, buyer acceptance, project messaging isolation, no fabricated payments, constraints, and Guardian reports. Check `/health` to see whether PayPal/AI keys are configured.

## Hackathon submission

See `docs/SUBMISSION_CHECKLIST.md`, `docs/DEVPOST_DESCRIPTION.md`, `docs/DEMO_SCRIPT.md` and `docs/ARCHITECTURE.md`. The official rules require a public repository with detectable open-source license, a functional demo or reproducible setup, and a public YouTube video less than three minutes. **The ZIP is not itself a submitted hackathon entry.**

## License

MIT — see `LICENSE`. LAPENG design and code in this ZIP are original for this prototype. Avoid copying screenshots or branded logos from reference mockups into a public project without clearing rights. No synthetic professional headshots are embedded in this build.

## Security hardening (revision 0.9.1)

This revision adds same-origin mutation checks, a 64-KiB JSON request limit, browser security headers (CSP, no framing, no sniffing, HSTS when configured for HTTPS), per-IP/account authentication throttling, 12-character minimum signup passwords, server-side logout and token revocation, participant-only Guardian/coalition analysis, confidential proposals, existing-target checks for reports, stronger PayPal order/amount/approval checks before capture, and regression tests (`tests/test_security.py`). No extra secrets are required for **local** use.

**Security boundary:** this is a local hackathon prototype, **not a production-hardened marketplace**. The in-memory rate limiter protects one Python process only and resets on restart. Use a reverse proxy, Redis/distributed throttling, persistent audit log, real email verification and account recovery, identity/KYC verification, malware scanning, fraud operations, privacy/legal review, infrastructure secrets management, monitoring, dependency pinning, and external penetration testing before accepting real customers or real money. Do not reuse personal passwords or submit real private customer data in this demo. The payment integration is **Sandbox-only** by design. Unconfigured payment or AI integrations cannot be portrayed as verified.

### Tests

Run `./VERIFY_WINDOWS.ps1` on PowerShell or `uv run python -m pytest -q` from the project root after setting up dependencies. For manual checks, use three separate test accounts (buyer, provider, outsider) and verify a private quote is hidden from the outsider, logout revokes the token, and payment always requires PayPal Sandbox approval.

**Messaging privacy:** early quotations are confidential. The shared project conversation opens for the buyer and **accepted** provider; pre-acceptance quote notes are available only to the buyer and the submitting provider. Multi-provider/private pre-sale messaging, video calls and notifications are not included in this MVP.
