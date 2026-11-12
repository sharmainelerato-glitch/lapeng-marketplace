"""Post-purchase self-service: transparent Sandbox receipts, tracked fulfilment,
rescheduling by mutual agreement, cancellation/replacement cases. No fake courier,
refund, escrow, invoices, seller disbursements or payments.
"""
import time, re
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

class CaseIn(BaseModel):
    kind:str=Field(pattern=r'^(cancel|replace|exchange|issue)$')
    reason:str=Field(min_length=10,max_length=700)
    listing_id:int|None=None
    replacement_option:str=Field(default='',max_length=120)
class DecisionIn(BaseModel):
    decision:str=Field(pattern=r'^(approved|declined)$')
    note:str=Field(default='',max_length=500)
class TrackingIn(BaseModel):
    status:str=Field(pattern=r'^(processing|packed|dispatched|in_transit|out_for_delivery|delivered|exception)$')
    carrier:str=Field(default='',max_length=90)
    tracking_ref:str=Field(default='',max_length=120)
    note:str=Field(default='',max_length=500)
class RescheduleIn(BaseModel):
    starts_at:int=Field(gt=0)
    ends_at:int=Field(gt=0)
    reason:str=Field(min_length=3,max_length=500)

def register(app,conn,current):
    router=APIRouter(prefix='/api/aftercare',tags=['aftercare'])
    clock=lambda:int(time.time())
    def one(db,sql,args=()):return db.execute(sql,args).fetchone()
    def many(db,sql,args=()):return [dict(r) for r in db.execute(sql,args)]
    with conn() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS aftercare_cases(
          id INTEGER PRIMARY KEY,order_id INTEGER NOT NULL REFERENCES shop_orders(id),actor_id INTEGER NOT NULL REFERENCES users(id),
          kind TEXT NOT NULL CHECK(kind IN ('cancel','replace','exchange','issue')),reason TEXT NOT NULL,
          listing_id INTEGER,replacement_option TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'requested',
          seller_note TEXT NOT NULL DEFAULT '',created INTEGER NOT NULL,updated INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS shipment_events(
          id INTEGER PRIMARY KEY,order_id INTEGER NOT NULL REFERENCES shop_orders(id),actor_id INTEGER NOT NULL REFERENCES users(id),
          status TEXT NOT NULL,carrier TEXT NOT NULL DEFAULT '',tracking_ref TEXT NOT NULL DEFAULT '',note TEXT NOT NULL DEFAULT '',created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS reschedule_requests(
          id INTEGER PRIMARY KEY,booking_id INTEGER NOT NULL REFERENCES service_bookings(id),requested_by INTEGER NOT NULL REFERENCES users(id),
          starts_at INTEGER NOT NULL,ends_at INTEGER NOT NULL,reason TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'requested',
          created INTEGER NOT NULL,updated INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_aftercare_cases_order ON aftercare_cases(order_id);
        CREATE INDEX IF NOT EXISTS idx_shipment_order ON shipment_events(order_id);
        CREATE INDEX IF NOT EXISTS idx_reschedule_booking ON reschedule_requests(booking_id);
        """)
    def order(db,id,uid):
        r=one(db,'SELECT o.*,p.owner_id,p.name provider_name FROM shop_orders o JOIN providers p ON p.id=o.provider_id WHERE o.id=?',(id,))
        if not r:raise HTTPException(404,'Order not found')
        if uid not in (r['buyer_id'],r['owner_id']):raise HTTPException(403,'Not an order participant')
        return r
    def booking(db,id,uid):
        r=one(db,'SELECT b.*,p.owner_id,l.title FROM service_bookings b JOIN providers p ON p.id=b.provider_id JOIN listings l ON l.id=b.listing_id WHERE b.id=?',(id,))
        if not r:raise HTTPException(404,'Booking not found')
        if uid not in (r['buyer_id'],r['owner_id']):raise HTTPException(403,'Not a booking participant')
        return r
    @router.get('/orders/{id}')
    def overview(id:int,u=Depends(current)):
        with conn() as db:
            r=order(db,id,u['id'])
            return {'order_id':id,'role':'buyer' if r['buyer_id']==u['id'] else 'seller',
              'events':many(db,'SELECT id,status,carrier,tracking_ref,note,created FROM shipment_events WHERE order_id=? ORDER BY id',(id,)),
              'cases':many(db,'SELECT id,kind,reason,listing_id,replacement_option,status,seller_note,created,updated FROM aftercare_cases WHERE order_id=? ORDER BY id DESC',(id,)),
              'payment_status':r['status'],'fulfilment':r['fulfilment_status'],
              'tracking_ref':r['tracking'],'sandbox_only':True,
              'notice':'Shipment events are seller-entered; tracking is not externally carrier-verified. Case approval is not a refund or replacement shipment.'}
    @router.get('/orders/{id}/receipt')
    def receipt(id:int,u=Depends(current)):
        with conn() as db:
            r=order(db,id,u['id'])
            if r['status'] not in ('paid','paid_attention_required'):raise HTTPException(409,'Receipt available only for verified completed Sandbox captures')
            items=many(db,'SELECT title,choice,qty,unit_price FROM shop_items WHERE order_id=?',(id,))
            return {'reference':f'LPG-O-{id:06d}','issued_at':r['created'],
              'merchant':r['provider_name'],'currency':r['currency'],
              'total':r['amount'],'items':items,'paypal_capture_reference':r['paypal_capture'],
              'payment_status':r['status'],'type':'Sandbox payment receipt — not a tax invoice',
              'notice':'Test payment only. This document is not proof of real funds paid, tax invoice, or seller payout.'}
    @router.post('/orders/{id}/cases')
    def new_case(id:int,x:CaseIn,u=Depends(current)):
        with conn() as db:
            db.execute('BEGIN IMMEDIATE');r=order(db,id,u['id'])
            if r['buyer_id']!=u['id']:raise HTTPException(403,'Only the buyer can request after-sales assistance')
            if r['status'] not in ('paid','paid_attention_required','awaiting_payment'):raise HTTPException(409,'Order is not eligible')
            if x.kind!='cancel' and r['status']!='paid':raise HTTPException(409,'Only paid purchases are eligible for exchanges or replacements')
            if x.kind=='cancel' and r['fulfilment_status'] in ('shipped','delivered','completed'):
                raise HTTPException(409,'Already dispatched or completed. Request a return or report an issue instead.')
            if x.kind in ('replace','exchange'):
                if r['fulfilment_status'] not in ('shipped','delivered','completed'):raise HTTPException(409,'Replacement and exchange requests require dispatched or delivered orders')
                if x.listing_id is None or not one(db,'SELECT id FROM shop_items WHERE order_id=? AND listing_id=?',(id,x.listing_id)):
                    raise HTTPException(422,'Choose a product actually in this order')
            if one(db,"SELECT 1 FROM aftercare_cases WHERE order_id=? AND status='requested' AND kind=?",(id,x.kind)):
                raise HTTPException(409,'A request of this type is already pending')
            cid=db.execute('INSERT INTO aftercare_cases(order_id,actor_id,kind,reason,listing_id,replacement_option,created,updated) VALUES(?,?,?,?,?,?,?,?)',
                (id,u['id'],x.kind,x.reason.strip(),x.listing_id,x.replacement_option,clock(),clock())).lastrowid
            return {'id':cid,'status':'requested','notice':'This is a request only. No payment reversal, inventory adjustment, shipping label or refund is triggered.'}
    @router.post('/cases/{id}/decision')
    def decide(id:int,x:DecisionIn,u=Depends(current)):
        with conn() as db:
            db.execute('BEGIN IMMEDIATE')
            case=one(db,'SELECT c.*,o.buyer_id,p.owner_id FROM aftercare_cases c JOIN shop_orders o ON o.id=c.order_id JOIN providers p ON p.id=o.provider_id WHERE c.id=?',(id,))
            if not case:raise HTTPException(404,'Case not found')
            if case['owner_id']!=u['id']:raise HTTPException(403,'Only the provider may decide')
            if case['status']!='requested':raise HTTPException(409,'Already decided')
            db.execute('UPDATE aftercare_cases SET status=?,seller_note=?,updated=? WHERE id=?',(x.decision,x.note,clock(),id))
            return {'status':x.decision,'notice':'Decision recorded. Payment refunds, replacement shipping and restocking require separate verified actions.'}
    @router.post('/orders/{id}/tracking')
    def add_tracking(id:int,x:TrackingIn,u=Depends(current)):
        with conn() as db:
            db.execute('BEGIN IMMEDIATE');r=order(db,id,u['id'])
            if r['owner_id']!=u['id']:raise HTTPException(403,'Only provider may update shipment')
            if r['status']!='paid':raise HTTPException(409,'Verified payment required')
            if len(many(db,'SELECT id FROM shipment_events WHERE order_id=?',(id,)))>=100:raise HTTPException(409,'Shipment history limit')
            if x.status in ('dispatched','in_transit','out_for_delivery','delivered') and not (x.tracking_ref or r['tracking']):
                raise HTTPException(422,'Provide a tracking reference for physical shipment updates')
            eid=db.execute('INSERT INTO shipment_events(order_id,actor_id,status,carrier,tracking_ref,note,created) VALUES(?,?,?,?,?,?,?)',
              (id,u['id'],x.status,x.carrier,x.tracking_ref or r['tracking'],x.note,clock())).lastrowid
            if x.tracking_ref:db.execute('UPDATE shop_orders SET tracking=?,updated=? WHERE id=?',(x.tracking_ref,clock(),id))
            return {'id':eid,'status':x.status,'carrier_verified':False}
    @router.get('/bookings/{id}/reschedules')
    def reschedules(id:int,u=Depends(current)):
        with conn() as db:
            booking(db,id,u['id'])
            return many(db,'SELECT id,requested_by,starts_at,ends_at,reason,status,created,updated FROM reschedule_requests WHERE booking_id=? ORDER BY id DESC',(id,))
    @router.post('/bookings/{id}/reschedules')
    def reschedule(id:int,x:RescheduleIn,u=Depends(current)):
        now=clock()
        if x.starts_at<=now or x.ends_at<=x.starts_at or x.ends_at-x.starts_at>86400 or x.starts_at>now+31536000:raise HTTPException(422,'Choose a future appointment up to 24 hours')
        with conn() as db:
            db.execute('BEGIN IMMEDIATE');b=booking(db,id,u['id'])
            if b['status'] not in ('requested','confirmed'):raise HTTPException(409,'Booking cannot be changed')
            if b['starts_at']-now<86400 and u['id']==b['buyer_id']:raise HTTPException(409,'Customer reschedules require at least 24 hours notice')
            if one(db,"SELECT 1 FROM reschedule_requests WHERE booking_id=? AND status='requested'",(id,)):raise HTTPException(409,'A change request is already pending')
            if one(db,"SELECT 1 FROM service_bookings WHERE id<>? AND provider_id=? AND status IN ('confirmed','requested') AND starts_at<? AND ends_at>?",(id,b['provider_id'],x.ends_at,x.starts_at)):
                raise HTTPException(409,'The proposed time overlaps another appointment')
            rid=db.execute('INSERT INTO reschedule_requests(booking_id,requested_by,starts_at,ends_at,reason,created,updated) VALUES(?,?,?,?,?,?,?)',
              (id,u['id'],x.starts_at,x.ends_at,x.reason,now,now)).lastrowid
            return {'id':rid,'status':'requested','notice':'Booking time stays unchanged until the other participant accepts.'}
    @router.post('/reschedules/{id}/decision')
    def reschedule_decision(id:int,x:DecisionIn,u=Depends(current)):
        with conn() as db:
            db.execute('BEGIN IMMEDIATE')
            r=one(db,'SELECT r.*,b.buyer_id,b.provider_id,b.status booking_status,p.owner_id FROM reschedule_requests r JOIN service_bookings b ON b.id=r.booking_id JOIN providers p ON p.id=b.provider_id WHERE r.id=?',(id,))
            if not r:raise HTTPException(404,'Change request not found')
            if u['id'] not in (r['buyer_id'],r['owner_id']) or r['requested_by']==u['id']:raise HTTPException(403,'Only the other booking participant can respond')
            if r['status']!='requested' or r['booking_status'] not in ('requested','confirmed'):raise HTTPException(409,'Change request is no longer active')
            if x.decision=='approved':
                if r['starts_at']<=clock():raise HTTPException(409,'Proposed time has passed')
                if one(db,"SELECT 1 FROM service_bookings WHERE id<>? AND provider_id=? AND status IN ('confirmed','requested') AND starts_at<? AND ends_at>?",(r['booking_id'],r['provider_id'],r['ends_at'],r['starts_at'])):
                    raise HTTPException(409,'Proposed time has been booked')
                db.execute('UPDATE service_bookings SET starts_at=?,ends_at=? WHERE id=?',(r['starts_at'],r['ends_at'],r['booking_id']))
            db.execute('UPDATE reschedule_requests SET status=?,updated=? WHERE id=?',(x.decision,clock(),id))
            return {'status':x.decision,'notice':'Booking updated only if accepted. Any payment changes must be handled separately.'}
    app.include_router(router)
