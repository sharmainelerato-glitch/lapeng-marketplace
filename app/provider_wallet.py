"""LAPENG provider wallet presentation API. Accounting visibility only.

Never represent platform Sandbox captures as funds held for a provider, and
never allow a client-supplied value to increase a wallet balance.
"""
from decimal import Decimal
from fastapi import APIRouter, Depends
from app.provider_payments import service_finance


def wallet_snapshot(db, user_id):
    businesses = service_finance(db, user_id)
    wallets = []
    for business in businesses:
        currencies = []
        for entry in business['by_currency']:
            # Captured payments to a platform Sandbox merchant are NOT a deposit
            # in a provider's legally/operationally funded wallet.
            currencies.append({
                'currency': entry['currency'],
                'tracked_gross': entry['gross'],
                'estimated_platform_commission': entry['commission_estimate'],
                'estimated_provider_earnings': entry['provider_before_processor_fees'],
                'available_balance': '0.00',
                'pending_settlement': entry['provider_before_processor_fees'],
                'paid_out': '0.00',
                'payment_count': entry['payments'],
                'status': 'sandbox_estimate_not_funded',
            })
        wallets.append({'provider_id': business['provider_id'],
                        'provider_name': business['provider_name'],
                        'currencies': currencies})
    return {'wallet_mode': 'sandbox_unfunded',
            'withdrawals_enabled': False,
            'transfers_enabled': False,
            'commission_percent': 5,
            'wallets': wallets,
            'notice': ('Pending settlement shows estimated earnings based on captured Sandbox service payments. '
                       'It is not money deposited in a wallet, reserved for payout or available to withdraw. '
                       'Seller onboarding, partner fees, verified settlements and persistent storage '
                       'are required before real wallet credits and withdrawals can be enabled.')}


def register(app, conn, current):
    router = APIRouter(prefix='/api/provider-wallet', tags=['provider-wallet'])

    @router.get('/overview')
    def overview(u=Depends(current)):
        with conn() as db:
            return wallet_snapshot(db, u['id'])

    app.include_router(router)
