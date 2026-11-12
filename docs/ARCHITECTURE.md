# Application architecture

Browser (one origin) → FastAPI JSON endpoints → SQLite (local state)

- Frontend: single-page application with hash routing, branded header, responsive minimal light UI.
- Auth: signed-in users hold randomized session bearer tokens, stored SHA-256-hashed server-side; passwords are PBKDF2-HMAC-SHA256 hashed with per-user salt. Login state is tab-scoped. This is prototype security, not hardened production auth.
- Roles: One identity, buyer and provider view switches. Server independently enforces ownership for requests, quotes, acceptance, payments, reviews, and messages.
- Opportunity Assembly: deterministic relevance and geographic eligibility scores; greedy capacity-constrained allocation; explicit USD budgets and estimated costs; model explanation is grounded in the resulting structured records.
- Guardian: transparent report records; warning signals with cautious interpretations; review eligibility anchored to completed payment.
- PayPal: backend OAuth client credentials → Orders v2 create → hosted buyer approval → backend capture → verify `COMPLETED`, currency and value → store event. Uses one sandbox merchant, not merchant splits.
- AI: OpenAI-compatible `/chat/completions`; if unavailable the system reports rules-only mode rather than fabricating an AI response.

Future: managed PostgreSQL, API idempotency, rate-limited identity provider, privacy workflow, verified webhooks, compliance enforcement, stronger transactional guarantees and merchant partner onboarding.
