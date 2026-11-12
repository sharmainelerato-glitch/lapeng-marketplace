# LAPENG Hackathon build — honest status

## Locally tested
- Python API boot and seed; `/health`, provider index and favicon endpoints
- Register and authenticate, provider ownership and quote permissions
- Buyer-only acceptance and private project chat access
- Guardian report persistence and review requiring verified payment
- Deterministic coalition endpoint (rules-only when no model credential)
- Missing PayPal credentials produce clear 503 instead of a false success
- JavaScript parser syntax via Node (`node --check static/app.js`)

## Not tested in this environment
- Real PayPal Sandbox OAuth, external payer approval and final capture (user credentials needed)
- External OpenAI-compatible inference (API key needed)
- End-to-end visual interaction in a browser (browser automation was blocked by the execution environment)
- Public hosting, cross-browser/mobile compatibility and independent accessibility audit

## Intentionally future scope
Production identity verification, trust badge providers, report adjudication, photo/file uploads, true live voice/video chat, live multiparty PayPal settlements, escrow, digital service milestone disbursement, real ratings from commerce users and international regulations.

### Security update 0.9.1
- Added server-side session revocation on logout and regression tests.
- Fixed confidential quotation visibility: only buyer and submitting provider can read proposed terms.
- Blocked unauthorized AI safety and coalition analysis of private requests.
- Enforced origin and request-size checks, rate limiting for auth/AI/payment endpoints, stronger signup passwords and defensive headers.
- Added independent PayPal Sandbox order ownership/amount and approval reconciliation before capture; prevented displaying raw upstream payment error bodies.
- Added target-existence checks for user reports and blocked late quotations on closed requests.
- Still a **sandbox-only prototype** requiring real payment/AI credentials and production-grade infrastructure before public release.
- Kept shared project messages visible only to the buyer and accepted provider. Quoting providers cannot read another provider's private negotiation messages.
