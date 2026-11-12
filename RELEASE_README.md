# LAPENG — buyer/provider release candidate (12 November 2026)

## Changes in this release
- Checkout step 2 continues to PayPal Sandbox without replacing the verified capture flow.
- Buyer delivery address saved on the authenticated account in SQLite and accessible across browsers using the same server.
- Buyer can edit the address of an order while its fulfilment status is pending or processing; the server blocks edits after shipping, delivery or completion.
- Buyer/provider owner checks at the API layer; updates use a status-conditional database operation.
- Unused development copies omitted: Windows `.venv`, duplicate backups, historical database snapshots, and secrets.

## Existing flows
Buyer: browse listings, cart/checkout, orders, reviews, saved listings, bookings, service requests, conversations, delivery support.
Provider: storefront/listings and photos, client requests/proposals, order fulfilment, project milestones, messaging, returns and settlement estimates.

## Critical limits (do not claim in submission that these are live)
- PayPal *Sandbox* only. No real payouts, no automatic ZAR conversion, and no production settlement.
- Digital/service project payment policies differ from physical shopping cart checkout.
- Carrier shipping rates, shipping taxes and actual logistics integrations are not calculated.
- Database-backed address changes require all devices to connect to the same deployed backend/database. SQLite on a single local machine is not cloud durable.
- Updating an order address does not automatically notify a shipping carrier or stop a label already printed; provider must act before shipment.
- Existing historical tests are not all passing: the current baseline has obsolete service/location expectations, plus shared rate-limit fixtures.

## Install
1. Back up your existing `LAPENG_Hackathon` directory, especially `.env`, `lapeng.sqlite3` and `uploads`.
2. Run `INSTALL_RELEASE_WINDOWS.ps1` from PowerShell, specifying your existing project directory.
3. Keep your existing `.env` and SQLite database. New tables are created automatically on app startup.
4. Restart your backend and refresh the browser; verify buyer and provider journeys using a test account.

## Validation performed
- Python compileall passes.
- JavaScript `node --check` passes.
- New targeted address tests: 2 passed.
- Full legacy test suite still requires repair before release; not represented as passing.
