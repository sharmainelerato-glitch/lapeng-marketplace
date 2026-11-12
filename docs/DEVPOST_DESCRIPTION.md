# LAPENG: Local Roots, Global Opportunities

**Tagline:** Find what you need. Discover who can help. Grow together.

## Inspiration

Small businesses, informal traders, tradespeople, and freelancers often have valuable skills but limited visibility and capacity. Existing marketplaces tend to isolate buying, professional services and business collaboration. LAPENG is designed to connect local communities to wider markets while helping independent people complete opportunities collaboratively.

## What it does

LAPENG offers a single identity with switchable Buyer and Provider workspaces. People discover local or remote providers, create storefronts, post requests, submit quotes, discuss project scope and agree to terms. Its Opportunity Assembly engine uses capacity, relevance and price constraints to construct transparent multi-provider proposals. With AI enabled, a conversational analysis explains evidence, fairness and uncertainty. Guardian provides complaints, permission checks and payment-based review eligibility. A PayPal Sandbox integration manages orders and captures without claiming real funds moved.

## How we built it

FastAPI, SQLite, vanilla JavaScript/CSS, Python's deterministic coalition allocator, an optional OpenAI-compatible chat completion API, PayPal REST Orders v2 Sandbox with OAuth, and pytest tests. No UI frameworks or remote image dependencies. Original SVG favicon.

## Technical challenge

Separating AI-generated language from operational truth: model text never determines payment status or invents capacity. The backend enforces access controls, budget and capacity calculations, and validates PayPal capture status and amount against accepted proposals.

## 5IR impact

Community-first inclusion, local and remote skills, human approval, fair opportunity allocation, traceable records and honest uncertainty. The MVP demonstrates those workflows but does not establish actual measured economic impact.

## What remains

Production identity verification, approved live marketplace seller onboarding, shipping integrations, cross-border compliance, real distributed payouts, advanced fraud moderation and longitudinal evaluation are future work.

## Tools used

PayPal Developer Platform / Sandbox, FastAPI, SQLite, pytest, Python, HTML, CSS, JavaScript, optional OpenAI-compatible AI endpoint. Report only the actual model you connect and successfully test.
