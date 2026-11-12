"""PayPal Sandbox webhook verification and moderator-gated full refunds.

Never treat merchant Sandbox receipts as seller payouts. Real partner fees and live
payouts require separate PayPal approval. Payment webhook records are verified,
but the browser capture route remains responsible for inventory reconciliation.
"""
import json
import os
import re
import time
from fastapi import APIRouter, Depends, Header, HTTPException, Request


def register(app, conn, current, paypal_api):
    router = APIRouter(prefix='/api/paypal-ops', tags=['payment-operations'])
    with conn() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS paypal_webhook_events(
          event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL, resource_id TEXT NOT NULL,
          received INTEGER NOT NULL, verified INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS paypal_refund_operations(
          order_id INTEGER PRIMARY KEY REFERENCES shop_orders(id),
          return_id INTEGER NOT NULL REFERENCES shop_returns(id),
          operator_id INTEGER NOT NULL REFERENCES users(id),
          capture_id TEXT NOT NULL, refund_id TEXT, state TEXT NOT NULL,
          amount INTEGER NOT NULL, currency TEXT NOT NULL, updated INTEGER NOT NULL
        );
        ''')

    def moderator(user):
        approved={int(x.strip()) for x in os.getenv('APP_MODERATOR_USER_IDS','').split(',') if x.strip().isdigit()}
        if not approved or user['id'] not in approved:
            raise HTTPException(403,'Authorised platform operator required')

    @router.post('/webhook')
    async def webhook(request:Request,
        transmission_id:str|None=Header(default=None, alias='paypal-transmission-id'),
        transmission_time:str|None=Header(default=None, alias='paypal-transmission-time'),
        transmission_sig:str|None=Header(default=None, alias='paypal-transmission-sig'),
        cert_url:str|None=Header(default=None, alias='paypal-cert-url'),
        auth_algo:str|None=Header(default=None, alias='paypal-auth-algo')):
        webhook_id=os.getenv('PAYPAL_WEBHOOK_ID','').strip()
        if not webhook_id:
            raise HTTPException(503,'Webhook verification is not configured')
        if not all((transmission_id,transmission_time,transmission_sig,cert_url,auth_algo)):
            raise HTTPException(400,'Missing PayPal webhook signature headers')
        try:event=await request.json()
        except (ValueError,UnicodeDecodeError):raise HTTPException(400,'Invalid webhook JSON')
        if not isinstance(event,dict) or not isinstance(event.get('id'),str) or not isinstance(event.get('event_type'),str):
            raise HTTPException(400,'Invalid PayPal event')
        # Verify with PayPal using OUR Sandbox OAuth token, not caller-provided trust.
        verification=await paypal_api('POST','/v1/notifications/verify-webhook-signature',{
            'transmission_id':transmission_id,'transmission_time':transmission_time,
            'transmission_sig':transmission_sig,'cert_url':cert_url,
            'auth_algo':auth_algo,'webhook_id':webhook_id,'webhook_event':event})
        if verification.get('verification_status')!='SUCCESS':
            raise HTTPException(403,'Webhook signature not verified')
        resource=event.get('resource') or {}
        event_id=event['id'][:150]
        event_type=event['event_type'][:100]
        resource_id=str(resource.get('id',''))[:150] if isinstance(resource,dict) else ''
        with conn() as db:
            result=db.execute('INSERT OR IGNORE INTO paypal_webhook_events(event_id,event_type,resource_id,received) VALUES(?,?,?,?)',
                (event_id,event_type,resource_id,int(time.time())))
        # Intentionally do NOT mark paid or refund on the basis of a webhook alone;
        # independent PayPal capture verification and inventory checks are needed.
        return {'received':True,'duplicate':result.rowcount==0}

    @router.post('/orders/{order_id}/refund')
    async def full_refund(order_id:int,u=Depends(current)):
        moderator(u)
        if os.getenv('PAYPAL_MODE','sandbox')!='sandbox':
            raise HTTPException(503,'Only Sandbox refunds are enabled')
        with conn() as db:
            db.execute('BEGIN IMMEDIATE')
            item=db.execute('''SELECT o.id,o.amount,o.currency,o.status,o.paypal_capture,
                r.id return_id FROM shop_orders o JOIN shop_returns r ON r.order_id=o.id
                WHERE o.id=? AND r.status='approved' ORDER BY r.id DESC LIMIT 1''',(order_id,)).fetchone()
            if not item:raise HTTPException(409,'A seller-approved return is required')
            if item['status']!='paid' or not item['paypal_capture']:
                raise HTTPException(409,'A verified, non-disputed paid capture is required')
            previous=db.execute('SELECT * FROM paypal_refund_operations WHERE order_id=?',(order_id,)).fetchone()
            if previous:raise HTTPException(409,'Refund already initiated or awaiting reconciliation; inspect PayPal before any further action')
            db.execute('INSERT INTO paypal_refund_operations(order_id,return_id,operator_id,capture_id,state,amount,currency,updated) VALUES(?,?,?,?,?,?,?,?)',
                (order_id,item['return_id'],u['id'],item['paypal_capture'],'requesting',item['amount'],item['currency'],int(time.time())))
            capture=item['paypal_capture']; currency=item['currency']; amount=item['amount']
        if not re.fullmatch(r'[A-Za-z0-9-]{5,120}',capture):raise HTTPException(409,'Invalid capture reference; manual review required')
        try:
            response=await paypal_api('POST',f'/v2/payments/captures/{capture}/refund',
                {},f'lapeng-refund-{order_id}')
        except Exception:
            with conn() as db:db.execute('UPDATE paypal_refund_operations SET state=?,updated=? WHERE order_id=?',
                ('needs_reconciliation',int(time.time()),order_id))
            raise HTTPException(502,'PayPal refund result is uncertain. Check the merchant Sandbox transaction before doing anything else; retries are blocked.')
        refund_id=str(response.get('id',''))
        status=response.get('status','')
        status='completed' if refund_id and status=='COMPLETED' else 'pending_review'
        with conn() as db:
            db.execute('UPDATE paypal_refund_operations SET state=?,refund_id=?,updated=? WHERE order_id=?',
                (status,refund_id,int(time.time()),order_id))
        return {'order_id':order_id,'refund_status':status,'refund_reference':refund_id,
                'note':'PayPal Sandbox operation only; no automatic stock restock or seller disbursement'}

    @router.get('/orders/{order_id}/refund-status')
    def refund_status(order_id:int,u=Depends(current)):
        with conn() as db:
            order=db.execute('SELECT o.buyer_id,p.owner_id FROM shop_orders o JOIN providers p ON p.id=o.provider_id WHERE o.id=?',(order_id,)).fetchone()
            if not order:raise HTTPException(404,'Order not found')
            configured={int(x.strip()) for x in os.getenv('APP_MODERATOR_USER_IDS','').split(',') if x.strip().isdigit()}
            if u['id'] not in (order['buyer_id'],order['owner_id']) and u['id'] not in configured:
                raise HTTPException(403,'Not an order participant')
            row=db.execute('SELECT state,refund_id,updated FROM paypal_refund_operations WHERE order_id=?',(order_id,)).fetchone()
            return {'order_id':order_id,'refund':dict(row) if row else None}

    app.include_router(router)
