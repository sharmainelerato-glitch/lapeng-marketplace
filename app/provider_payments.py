"""Read-only service earnings and explicit PayPal marketplace readiness.

No money movement. A PayPal Sandbox capture to LAPENG's merchant account
is NOT a seller payout, a partner fee, a held balance, or escrow.
"""
from decimal import Decimal, ROUND_HALF_UP
from fastapi import APIRouter, Depends

COMMISSION_BPS = 500

def breakdown(gross, currency):
    value = Decimal(str(gross))
    if not value.is_finite() or value < 0:
        raise ValueError('Gross must be finite and non-negative')
    fee = (value * Decimal(COMMISSION_BPS) / Decimal(10000)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return {'currency': currency, 'gross': f'{value:.2f}', 'commission_estimate': f'{fee:.2f}',
            'provider_before_processor_fees': f'{(value-fee):.2f}', 'paid_out': '0.00',
            'payout_status': 'not_connected'}

def service_finance(db, user_id):
    """Provider-owned, verified completed service captures only."""
    businesses = db.execute('SELECT id,name FROM providers WHERE owner_id=? ORDER BY id',(user_id,)).fetchall()
    result=[]
    for business in businesses:
        # JOIN through the accepted proposal to prevent buyer-controlled payment IDs
        # from disclosing another provider's financial data.
        verified=db.execute('''SELECT pay.id, pay.amount,pay.currency,pay.paypal_capture,pay.updated,
               req.title FROM payments pay
               JOIN proposals prop ON prop.id=pay.proposal_id AND prop.request_id=pay.request_id
               JOIN requests req ON req.id=pay.request_id AND req.buyer_id=pay.buyer_id
               WHERE prop.provider_id=? AND prop.status='accepted'
               AND pay.status='COMPLETED' AND pay.paypal_capture IS NOT NULL
               ORDER BY pay.id DESC LIMIT 200''',(business['id'],)).fetchall()
        orders=[]; by_currency={}
        for pay in verified:
            d=breakdown(pay['amount'],pay['currency'])
            orders.append({'payment_id':pay['id'],'title':pay['title'],**d,
                           'paypal_capture_recorded': True})
            cur=by_currency.setdefault(pay['currency'],{'currency':pay['currency'],'gross':Decimal('0'),
                'commission_estimate':Decimal('0'),'provider_before_processor_fees':Decimal('0'),
                'paid_out':Decimal('0'),'payments':0})
            cur['gross']+=Decimal(d['gross']);cur['commission_estimate']+=Decimal(d['commission_estimate'])
            cur['provider_before_processor_fees']+=Decimal(d['provider_before_processor_fees'])
            cur['payments']+=1
        summaries=[{k:(f'{v:.2f}' if isinstance(v,Decimal) else v) for k,v in row.items()} for row in by_currency.values()]
        result.append({'provider_id':business['id'],'provider_name':business['name'],
                       'by_currency':summaries,'verified_service_payments':orders})
    return result

def register(app, conn, current):
    router=APIRouter(prefix='/api/provider-payments',tags=['provider-payment-readiness'])
    @router.get('/overview')
    def overview(u=Depends(current)):
        with conn() as db:
            businesses=service_finance(db,u['id'])
        return {'mode':'sandbox_accounting_only', 'commission_rate_percent':5,
                'businesses':businesses,'seller_onboarding_status':'not_connected',
                'platform_fee_status':'not_connected','provider_payout_status':'not_connected',
                'seller_payouts_executed':False,
                'warning':'Captures to the LAPENG Sandbox merchant are NOT seller payouts. Estimated 5% commission is not a collected partner fee; PayPal fees may apply. No funds are held in escrow.'}
    @router.get('/requirements')
    def requirements(u=Depends(current)):
        return {'paypal_multiparty_partner_approval_required':True,'sandbox_supported_after_partner_setup':True,
                'required_capabilities':['seller onboarding','seller consent and PayPal merchant eligibility',
                  'partner fee capability','server-verified payee and payment status','refunds and disputes handling'],
                'live_payouts_enabled':False,'sandbox_payouts_enabled':False,
                'next_action':'Apply for PayPal marketplace/partner access; configure verified seller onboarding and partner credentials before enabling transfers.',
                'docs':'https://developer.paypal.com/platforms/get-started'}
    app.include_router(router)
