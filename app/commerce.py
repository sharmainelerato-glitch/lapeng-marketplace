"""LAPENG checkout / fulfilment MVP. Only real PayPal Sandbox captures are marked paid.
Single-provider, single-currency checkout. No FX, payout or escrow is represented as complete.
"""
import json, sqlite3, time, re
from decimal import Decimal, ROUND_HALF_UP
from os import getenv

PAYPAL_TEST_CURRENCIES=frozenset(('USD','EUR','GBP','CAD','AUD','NZD'))
LISTING_CURRENCIES=PAYPAL_TEST_CURRENCIES | {'ZAR'}
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

def is_shop_product(kind):
    """Use the actual listing type, not the provider category or description."""
    return str(kind or '').strip().lower() in {'product', 'products', 'digital product', 'digital products'}

class CartLine(BaseModel):
    listing_id:int=Field(gt=0)
    option:str=Field(default='',max_length=120) # variant SKU/name OR service package name
    quantity:int=Field(ge=1,le=100)

class CheckoutIn(BaseModel):
    buyer_latitude:float|None=Field(default=None,ge=-90,le=90)
    buyer_longitude:float|None=Field(default=None,ge=-180,le=180)
    delivery_address:str=Field(default='',max_length=500)
    delivery_note:str=Field(default='',max_length=500)
    delivery_method:str=Field(default='arrange',pattern=r'^(arrange|pickup|local_delivery|shipping|digital)$')
    delivery_country:str=Field(default='',max_length=90)

class SavedAddressIn(BaseModel):
    delivery_address:str=Field(min_length=12,max_length=500)
    delivery_country:str=Field(min_length=2,max_length=90)

class OrderAddressIn(BaseModel):
    delivery_address:str=Field(min_length=12,max_length=500)

class StatusIn(BaseModel):
    status:str
    tracking:str=Field(default='',max_length=100)

class ReturnIn(BaseModel):
    reason:str=Field(min_length=10,max_length=700)

class BookIn(BaseModel):
    listing_id:int=Field(gt=0)
    starts_at:int=Field(gt=0)
    ends_at:int=Field(gt=0)
    note:str=Field(default='',max_length=500)
    buyer_latitude:float|None=Field(default=None,ge=-90,le=90)
    buyer_longitude:float|None=Field(default=None,ge=-180,le=180)

class MilestoneIn(BaseModel):
    title:str=Field(min_length=3,max_length=130)
    details:str=Field(default='',max_length=700)
    due_at:int|None=None

class ProjectUpdateIn(BaseModel):
    status:str
    note:str=Field(default='',max_length=500)


def register(app,conn,current,paypal_api,throttle):
    router=APIRouter(prefix='/api/commerce',tags=['commerce'])
    def now():return int(time.time())
    COMMISSION_BPS=500  # Agreed 5%; basis points make pricing unambiguous.
    def commission_for(amount):
        return float((Decimal(str(amount))*Decimal(COMMISSION_BPS)/Decimal(10000)).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP))

    def fetch(db,q,values=()):return db.execute(q,values).fetchone()
    def asdict(x):return dict(x) if x else None
    def many(db,q,values=()):return [dict(x) for x in db.execute(q,values)]

    with conn() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS cart_lines(id INTEGER PRIMARY KEY,buyer_id INTEGER NOT NULL REFERENCES users(id),listing_id INTEGER NOT NULL REFERENCES listings(id),choice TEXT NOT NULL DEFAULT '',qty INTEGER NOT NULL,CHECK(qty>0),UNIQUE(buyer_id,listing_id,choice));
        CREATE TABLE IF NOT EXISTS shop_orders(id INTEGER PRIMARY KEY,buyer_id INTEGER NOT NULL REFERENCES users(id),provider_id INTEGER NOT NULL REFERENCES providers(id),amount INTEGER NOT NULL,currency TEXT NOT NULL DEFAULT 'USD',delivery_address TEXT NOT NULL DEFAULT '',delivery_note TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'awaiting_payment',fulfilment_status TEXT NOT NULL DEFAULT 'pending',paypal_order TEXT UNIQUE,paypal_capture TEXT,created INTEGER NOT NULL,updated INTEGER NOT NULL,tracking TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS shop_items(id INTEGER PRIMARY KEY,order_id INTEGER NOT NULL REFERENCES shop_orders(id),listing_id INTEGER NOT NULL REFERENCES listings(id),title TEXT NOT NULL,choice TEXT NOT NULL DEFAULT '',qty INTEGER NOT NULL,unit_price INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS shop_returns(id INTEGER PRIMARY KEY,order_id INTEGER NOT NULL REFERENCES shop_orders(id),author_id INTEGER NOT NULL REFERENCES users(id),reason TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'requested',created INTEGER NOT NULL,updated INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS shop_reviews(id INTEGER PRIMARY KEY,order_id INTEGER NOT NULL REFERENCES shop_orders(id),listing_id INTEGER NOT NULL REFERENCES listings(id),buyer_id INTEGER NOT NULL REFERENCES users(id),provider_id INTEGER NOT NULL REFERENCES providers(id),score INTEGER NOT NULL CHECK(score BETWEEN 1 AND 5),text TEXT NOT NULL,created INTEGER NOT NULL,UNIQUE(order_id,listing_id,buyer_id));
        CREATE TABLE IF NOT EXISTS service_bookings(id INTEGER PRIMARY KEY,listing_id INTEGER NOT NULL REFERENCES listings(id),buyer_id INTEGER NOT NULL REFERENCES users(id),provider_id INTEGER NOT NULL REFERENCES providers(id),starts_at INTEGER NOT NULL,ends_at INTEGER NOT NULL,note TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'requested',created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS project_milestones(id INTEGER PRIMARY KEY,order_id INTEGER NOT NULL REFERENCES shop_orders(id),title TEXT NOT NULL,details TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'planned',due_at INTEGER,created INTEGER NOT NULL,updated INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS order_notes(id INTEGER PRIMARY KEY,order_id INTEGER NOT NULL REFERENCES shop_orders(id),actor_id INTEGER NOT NULL REFERENCES users(id),body TEXT NOT NULL,created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS buyer_delivery_addresses(user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,delivery_address TEXT NOT NULL,delivery_country TEXT NOT NULL,updated INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS saved_listings(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),listing_id INTEGER NOT NULL REFERENCES listings(id),created INTEGER NOT NULL, UNIQUE(user_id,listing_id));
        CREATE TABLE IF NOT EXISTS order_finance_events(id INTEGER PRIMARY KEY,order_id INTEGER NOT NULL REFERENCES shop_orders(id),event_type TEXT NOT NULL,amount REAL NOT NULL,currency TEXT NOT NULL,source TEXT NOT NULL,created INTEGER NOT NULL,UNIQUE(order_id,event_type,source));
        ''')

    def selected(listing,choice):
        variants=json.loads(listing['variants_json'] or '[]')
        packages=json.loads(listing['packages_json'] or '[]')
        if variants:
            match=next((v for v in variants if (v.get('sku') or v.get('name'))==choice),None)
            if not match:raise HTTPException(422,'Select a valid size, colour or other variant')
            return int(match['price']),int(match['stock']),'variant'
        if packages:
            match=next((p for p in packages if p['name']==choice),None)
            if not match:raise HTTPException(422,'Select an available service package')
            return int(match['price']),int(listing['stock']),'package'
        if choice:raise HTTPException(422,'This listing has no selectable option')
        return int(listing['price']),int(listing['stock']),'simple'

    def cart_detail(db,uid):
        data=many(db,'SELECT cl.*,l.title,l.price,l.stock,l.variants_json,l.packages_json,l.kind,l.currency,(SELECT im.filename FROM portfolio_images im WHERE im.listing_id=l.id ORDER BY im.id DESC LIMIT 1) photo,p.name provider_name,p.id provider_id,p.owner_id FROM cart_lines cl JOIN listings l ON l.id=cl.listing_id JOIN providers p ON p.id=l.provider_id WHERE cl.buyer_id=? ORDER BY cl.id',(uid,))
        out=[]
        for line in data:
            try:
                price,available,kind=selected(line,line['choice'])
                warning='' if available>=line['qty'] else 'Not enough stock or capacity'
            except HTTPException as ex:
                price,available,kind,warning=0,0,'invalid',ex.detail
            out.append({k:line[k] for k in ('id','listing_id','title','choice','qty','provider_name','provider_id','currency') } | {'price':price,'subtotal':price*line['qty'],'available':available,'type':kind,'warning':warning,'listing_kind':line['kind'],'variants':json.loads(line['variants_json'] or '[]'),'photo_url':'/uploads/'+line['photo'] if line['photo'] else None})
        return out

    @router.get('/payment-capabilities')
    def payment_capabilities():
        return {'mode':'sandbox','supported_checkout_currencies':sorted(PAYPAL_TEST_CURRENCIES),
                'listing_currencies':sorted(LISTING_CURRENCIES),'automatic_fx':False,
                'zar_checkout':False,'seller_onboarding_connected':False,
                'seller_payouts_connected':False,
                'payment_methods_note':'Approval and available payment methods depend on merchant and buyer country/account. Sandbox credentials are required.',
                'next_step':'PayPal Complete Payments Platform requires approval for live multiparty seller onboarding and payouts.'}

    @router.get('/catalogue')
    def catalogue(q:str='',limit:int=40):
        if len(q)>130 or limit<1 or limit>80:raise HTTPException(422,'Invalid search')
        with conn() as db:
            query='''SELECT l.id,l.provider_id,l.title,l.description,l.kind,l.price,l.stock,
                            l.variants_json,l.packages_json,l.catalog_category,l.currency,
                            p.name provider_name,p.city,p.country,p.owner_id,
                            (SELECT filename FROM portfolio_images im WHERE im.listing_id=l.id ORDER BY im.id DESC LIMIT 1) photo
                     FROM listings l JOIN providers p ON p.id=l.provider_id
                     WHERE 1=1'''
            args=[]
            if q:
                if re.fullmatch(r'LPG-L-[0-9]{1,10}',q.strip().upper()):
                    query+=' AND l.id=?';args=[int(q.strip().upper().split('-')[-1])]
                else:
                    query+=' AND (l.title LIKE ? OR l.description LIKE ? OR p.name LIKE ? OR l.catalog_category LIKE ?)';args=['%'+q+'%']*4
            records=many(db,query+' ORDER BY l.id DESC LIMIT ?',(*args,limit))
            return [{**{k:r[k] for k in ('id','provider_id','title','description','kind','price','stock','catalog_category','currency','provider_name','city','country')},'public_id':f'LPG-L-{r["id"]:06d}','demo_only':r['owner_id'] is None,'photo_url':'/uploads/'+r['photo'] if r['photo'] else None,'variants':json.loads(r['variants_json'] or '[]'),'packages':json.loads(r['packages_json'] or '[]')} for r in records]

    @router.get('/cart')
    def get_cart(u=Depends(current)):
        with conn() as db:
            lines=cart_detail(db,u['id'])
            currencies={i['currency'] for i in lines}
            curr=next(iter(currencies)) if len(currencies)==1 else None
            return {'lines':lines,'total':sum(i['subtotal'] for i in lines) if curr else None,'currency':curr,'checkout_supported':bool(curr in PAYPAL_TEST_CURRENCIES) and bool(lines) and len({i['provider_id'] for i in lines})==1 and all(is_shop_product(i['listing_kind']) and not i['warning'] for i in lines),'note':'Single-provider, single-currency Sandbox checkout only. No automatic FX or seller payouts.'}

    @router.post('/cart')
    def add_cart(x:CartLine,u=Depends(current)):
        with conn() as db:
            l=fetch(db,'SELECT l.*,p.owner_id FROM listings l JOIN providers p ON p.id=l.provider_id WHERE l.id=?',(x.listing_id,))
            if not l:raise HTTPException(404,'Listing not found')
            if not is_shop_product(l['kind']):raise HTTPException(422,'Services are arranged through provider messages and requests, not the product cart')
            if l['owner_id'] is None:raise HTTPException(403,'Example listings cannot be purchased')
            if l['owner_id']==u['id']:raise HTTPException(403,'Cannot buy your own listing')
            price,available,_=selected(l,x.option)
            if price<1 or available<x.quantity:raise HTTPException(409,'This option is not available in the requested quantity')
            previous=fetch(db,'SELECT qty FROM cart_lines WHERE buyer_id=? AND listing_id=? AND choice=?',(u['id'],x.listing_id,x.option))
            if previous and previous['qty']+x.quantity>available:raise HTTPException(409,'Requested quantity exceeds availability')
            db.execute('INSERT INTO cart_lines(buyer_id,listing_id,choice,qty) VALUES(?,?,?,?) ON CONFLICT(buyer_id,listing_id,choice) DO UPDATE SET qty=qty+excluded.qty',(u['id'],x.listing_id,x.option,x.quantity))
            return {'ok':True}

    class CartEdit(BaseModel):
        choice:str=Field(default='',max_length=120)
        quantity:int=Field(ge=1,le=100)

    @router.patch('/cart/{line_id}')
    def edit_cart(line_id:int,x:CartEdit,u=Depends(current)):
        with conn() as db:
            old=fetch(db,'SELECT * FROM cart_lines WHERE id=? AND buyer_id=?',(line_id,u['id']))
            if not old:raise HTTPException(404,'Cart item not found')
            item=fetch(db,'SELECT * FROM listings WHERE id=?',(old['listing_id'],))
            if not item or not is_shop_product(item['kind']):raise HTTPException(422,'Only products can be edited in the shopping cart')
            price,available,_=selected(item,x.choice)
            if price<1 or available<x.quantity:raise HTTPException(409,'This size, colour or quantity is not available')
            other=fetch(db,'SELECT id,qty FROM cart_lines WHERE buyer_id=? AND listing_id=? AND choice=? AND id<>?',(u['id'],old['listing_id'],x.choice,line_id))
            if other:
                if other['qty']+x.quantity>available:raise HTTPException(409,'Requested quantity exceeds stock available in your cart')
                db.execute('UPDATE cart_lines SET qty=? WHERE id=? AND buyer_id=?',(other['qty']+x.quantity,other['id'],u['id']))
                db.execute('DELETE FROM cart_lines WHERE id=? AND buyer_id=?',(line_id,u['id']))
            else:
                db.execute('UPDATE cart_lines SET choice=?,qty=? WHERE id=? AND buyer_id=?',(x.choice,x.quantity,line_id,u['id']))
        return {'ok':True}

    @router.delete('/cart/{line_id}')
    def remove_cart(line_id:int,u=Depends(current)):
        with conn() as db:
            db.execute('DELETE FROM cart_lines WHERE id=? AND buyer_id=?',(line_id,u['id']))
        return {'ok':True}

    def owned_order(db,order_id,uid):
        order=fetch(db,'SELECT o.*,p.owner_id FROM shop_orders o JOIN providers p ON p.id=o.provider_id WHERE o.id=?',(order_id,))
        if not order:raise HTTPException(404,'Order not found')
        if uid not in (order['buyer_id'],order['owner_id']):raise HTTPException(403,'Not an order participant')
        return order

    def order_detail(db,order):
        order=dict(order)
        order.pop('owner_id',None)
        order['items']=many(db,'SELECT id,listing_id,title,choice,qty,unit_price FROM shop_items WHERE order_id=?',(order['id'],))
        order['returns']=many(db,'SELECT id,reason,status,created FROM shop_returns WHERE order_id=?',(order['id'],))
        order['milestones']=many(db,'SELECT * FROM project_milestones WHERE order_id=? ORDER BY id',(order['id'],))
        order['notes']=many(db,'SELECT n.body,n.created,u.name author FROM order_notes n JOIN users u ON u.id=n.actor_id WHERE order_id=? ORDER BY n.id',(order['id'],))
        return order

    @router.get('/delivery-address')
    def get_delivery_address(u=Depends(current)):
        with conn() as db:
            saved=fetch(db,'SELECT delivery_address,delivery_country,updated FROM buyer_delivery_addresses WHERE user_id=?',(u['id'],))
            return asdict(saved)

    @router.put('/delivery-address')
    def put_delivery_address(x:SavedAddressIn,u=Depends(current)):
        address=x.delivery_address.strip()
        country=x.delivery_country.strip()
        if len(address)<12 or len(country)<2:raise HTTPException(422,'Enter a complete address and country')
        with conn() as db:
            db.execute('INSERT INTO buyer_delivery_addresses(user_id,delivery_address,delivery_country,updated) VALUES(?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET delivery_address=excluded.delivery_address,delivery_country=excluded.delivery_country,updated=excluded.updated',(u['id'],address,country,now()))
        return {'delivery_address':address,'delivery_country':country,'saved':True}

    @router.patch('/orders/{order_id}/delivery-address')
    def change_order_delivery_address(order_id:int,x:OrderAddressIn,u=Depends(current)):
        address=x.delivery_address.strip()
        if len(address)<12:raise HTTPException(422,'Enter a complete delivery address')
        with conn() as db:
            # Atomic status guard also prevents edits racing with the seller marking an order shipped.
            result=db.execute("UPDATE shop_orders SET delivery_address=?,updated=? WHERE id=? AND buyer_id=? AND fulfilment_status IN ('pending','processing') AND status IN ('awaiting_payment','paid','paid_attention_required')",(address,now(),order_id,u['id']))
            if result.rowcount!=1:
                exists=fetch(db,'SELECT buyer_id,fulfilment_status FROM shop_orders WHERE id=?',(order_id,))
                if not exists:raise HTTPException(404,'Order not found')
                if exists['buyer_id']!=u['id']:raise HTTPException(403,'Only the buyer can change their order address')
                raise HTTPException(409,'Delivery address is locked once an order is shipped or closed')
        return {'delivery_address':address,'updated':True}

    @router.get('/orders')
    def orders(u=Depends(current)):
        with conn() as db:
            orders=many(db,'SELECT o.*,p.name provider_name,p.owner_id FROM shop_orders o JOIN providers p ON p.id=o.provider_id WHERE o.buyer_id=? OR p.owner_id=? ORDER BY o.id DESC',(u['id'],u['id']))
            return [{**order_detail(db,o),'provider_name':o['provider_name'],'role':'buyer' if o['buyer_id']==u['id'] else 'seller'} for o in orders]

    @router.get('/orders/{order_id}')
    def get_order(order_id:int,u=Depends(current)):
        with conn() as db:return order_detail(db,owned_order(db,order_id,u['id']))

    @router.post('/checkout')
    async def checkout(details:CheckoutIn,u=Depends(current)):
        throttle('shop-create:'+str(u['id']),12,3600)
        from os import getenv
        if not getenv('PAYPAL_CLIENT_ID') or not getenv('PAYPAL_CLIENT_SECRET'):raise HTTPException(503,'Configure PayPal Sandbox credentials before checkout. No payment made.')
        with conn() as db:
            lines=cart_detail(db,u['id'])
            if not lines:raise HTTPException(409,'Cart is empty')
            if any(not is_shop_product(i['listing_kind']) for i in lines):raise HTTPException(409,'Services cannot be paid through the product cart. Contact the provider instead.')
            if len({l['provider_id'] for l in lines})!=1:raise HTTPException(409,'Checkout one provider at a time. Remove items from other sellers or use separate orders.')
            if any(l['warning'] or l['price']<1 for l in lines):raise HTTPException(409,'Resolve unavailable items in the cart before paying')
            # An on-site service cannot be bought as an international digital order.
            for line in lines:
                record=fetch(db,'SELECT l.kind listing_kind,p.remote,p.latitude,p.longitude,p.service_radius_km FROM listings l JOIN providers p ON p.id=l.provider_id WHERE l.id=?',(line['listing_id'],))
                service=any(word in record['listing_kind'].lower() for word in ('service','appointment','lesson','consult','session','tutor'))
                if service and not record['remote']:
                    if record['latitude'] is None or record['longitude'] is None:
                        raise HTTPException(409,'This local service provider must configure their service area before checkout')
                    if details.buyer_latitude is None or details.buyer_longitude is None:
                        raise HTTPException(422,'Enable nearby location before paying for an on-site service')
                    from app.main import distance_km
                    km=distance_km(details.buyer_latitude,details.buyer_longitude,record['latitude'],record['longitude'])
                    if km>record['service_radius_km']:
                        raise HTTPException(422,'This service is outside the provider service area. Choose a provider near you.')
            # Seller-published delivery rules are enforced when the buyer selects a specific mode.
            # They are indicative only: no carrier booking, taxes or shipping fees are included.
            delivery=fetch(db,'SELECT * FROM provider_delivery WHERE provider_id=?',(lines[0]['provider_id'],))
            if details.delivery_method=='local_delivery':
                if not delivery or not delivery['local_delivery']:raise HTTPException(422,'This provider has not enabled local delivery')
                if details.buyer_latitude is None or details.buyer_longitude is None:raise HTTPException(422,'Share a location to check local delivery coverage')
                p=fetch(db,'SELECT latitude,longitude FROM providers WHERE id=?',(lines[0]['provider_id'],))
                if not p or p['latitude'] is None or p['longitude'] is None:raise HTTPException(422,'Provider has not configured a delivery centre')
                from app.main import distance_km
                if distance_km(details.buyer_latitude,details.buyer_longitude,p['latitude'],p['longitude'])>delivery['delivery_radius_km']:raise HTTPException(422,'Outside this provider local-delivery area')
            elif details.delivery_method=='pickup':
                if delivery and not delivery['pickup_available']:raise HTTPException(422,'This provider does not offer collection')
            elif details.delivery_method=='shipping':
                if not delivery or not details.delivery_country.strip():raise HTTPException(422,'Specify the delivery country and verify seller shipping regions')
                regions=json.loads(delivery['shipping_regions_json'])
                if not any(details.delivery_country.casefold().strip()==r.casefold().strip() for r in regions):raise HTTPException(422,'Seller has not listed shipping to that country')
            # "arrange" is a quote/coordination request; no shipping entitlement is implied.
            currencies={l['currency'] for l in lines}
            if len(currencies)!=1:raise HTTPException(409,'Cart contains mixed currencies. Checkout separately by currency; no automatic conversion is offered.')
            currency=next(iter(currencies))
            if currency not in PAYPAL_TEST_CURRENCIES:raise HTTPException(422,f'{currency} PayPal checkout is unavailable. Do not convert or charge without a verified provider quote.')
            total=sum(l['subtotal'] for l in lines)
            if total>1000000:raise HTTPException(422,'Order amount exceeds MVP limit')
            # Physical orders need a delivery destination or explicit collection note.
            if not details.delivery_address.strip() and not details.delivery_note.strip():raise HTTPException(422,'Enter a delivery address or collection / digital delivery instructions')
            timestamp=now()
            order_id=db.execute('INSERT INTO shop_orders(buyer_id,provider_id,amount,currency,delivery_address,delivery_note,created,updated) VALUES(?,?,?,?,?,?,?,?)',(u['id'],lines[0]['provider_id'],total,currency,details.delivery_address,details.delivery_note,timestamp,timestamp)).lastrowid
            db.executemany('INSERT INTO shop_items(order_id,listing_id,title,choice,qty,unit_price) VALUES(?,?,?,?,?,?)',[(order_id,l['listing_id'],l['title'],l['choice'],l['qty'],l['price']) for l in lines])
        base=getenv('APP_BASE_URL','http://127.0.0.1:8000').rstrip('/')
        try:
            pay=await paypal_api('POST','/v2/checkout/orders',{'intent':'CAPTURE','purchase_units':[{'reference_id':'SHOP-'+str(order_id),'description':'LAPENG order '+str(order_id),'amount':{'currency_code':currency,'value':f'{total:.2f}'}}],'payment_source':{'paypal':{'experience_context':{'return_url':base+'/?shop_return='+str(order_id),'cancel_url':base+'/?shop_cancel='+str(order_id),'user_action':'PAY_NOW'}}}},'lapeng-shop-'+str(order_id))
        except Exception:
            # Pending local record remains explicit, never called paid.
            raise
        url=next((x['href'] for x in pay.get('links',[]) if x.get('rel') in ('payer-action','approve')),None)
        with conn() as db:db.execute('UPDATE shop_orders SET paypal_order=?,updated=? WHERE id=?',(pay['id'],now(),order_id))
        return {'order_id':order_id,'approve_url':url,'currency':currency,'status':'awaiting_payment'}

    @router.post('/orders/{order_id}/capture')
    async def capture(order_id:int,u=Depends(current)):
        throttle('shop-capture:'+str(u['id']),16,3600)
        with conn() as db:
            o=owned_order(db,order_id,u['id'])
            if o['buyer_id']!=u['id']:raise HTTPException(403,'Only buyer can verify checkout')
            if o['status'] in ('paid','paid_attention_required'):return {'status':o['status'],'already_captured':True}
            if not o['paypal_order']:raise HTTPException(409,'No PayPal checkout associated')
        check=await paypal_api('GET','/v2/checkout/orders/'+o['paypal_order'])
        if check.get('id')!=o['paypal_order'] or check.get('status') not in ('APPROVED','COMPLETED'):raise HTTPException(409,'PayPal approval not confirmed')
        if not any(p.get('reference_id')=='SHOP-'+str(order_id) and p.get('amount',{}).get('currency_code')==o['currency'] and p.get('amount',{}).get('value')==f"{o['amount']:.2f}" for p in check.get('purchase_units',[])):
            raise HTTPException(409,'PayPal amount or order reference mismatch')
        paid=check if check['status']=='COMPLETED' else await paypal_api('POST','/v2/checkout/orders/'+o['paypal_order']+'/capture',{},'lapeng-shop-capture-'+str(order_id))
        caps=[c for unit in paid.get('purchase_units',[]) for c in unit.get('payments',{}).get('captures',[])]
        capture_id=next((c.get('id') for c in caps if c.get('status')=='COMPLETED' and c.get('amount',{}).get('currency_code')==o['currency'] and c.get('amount',{}).get('value')==f"{o['amount']:.2f}"),None)
        if paid.get('status')!='COMPLETED' or not capture_id:return {'status':'pending_verification','verified':False}
        matched_capture=next((c for c in caps if c.get('id')==capture_id),{})
        breakdown=(matched_capture.get('seller_receivable_breakdown') or {}).get('paypal_fee') or {}
        fee_value=None
        if breakdown.get('currency_code')==o['currency']:
            try:
                parsed=Decimal(str(breakdown['value']))
                if parsed>=0 and parsed<=Decimal(str(o['amount'])):
                    fee_value=float(parsed.quantize(Decimal('0.01'),rounding=ROUND_HALF_UP))
            except (ValueError,ArithmeticError,KeyError):pass

        with conn() as db:
            db.execute('BEGIN IMMEDIATE')
            current_o=fetch(db,'SELECT status FROM shop_orders WHERE id=?',(order_id,))
            if current_o['status'] in ('paid','paid_attention_required'):return {'status':current_o['status'],'already_captured':True}
            items=many(db,'SELECT * FROM shop_items WHERE order_id=?',(order_id,))
            inventory_issue=False
            updates=[]
            for line in items:
                listing=fetch(db,'SELECT * FROM listings WHERE id=?',(line['listing_id'],))
                if not listing:
                    inventory_issue=True
                    continue
                variants=json.loads(listing['variants_json'] or '[]')
                if variants:
                    v=next((v for v in variants if (v.get('sku') or v.get('name'))==line['choice']),None)
                    if not v or v['stock']<line['qty']:
                        inventory_issue=True
                    else:
                        v['stock']-=line['qty']
                        updates.append(('variant',line['listing_id'],json.dumps(variants),sum(x['stock'] for x in variants)))
                elif listing['stock']<line['qty']:
                    inventory_issue=True
                else:
                    updates.append(('simple',line['listing_id'],line['qty'],None))
            if not inventory_issue:
                for kind,lid,value,total in updates:
                    if kind=='variant':db.execute('UPDATE listings SET variants_json=?,stock=? WHERE id=?',(value,total,lid))
                    else:db.execute('UPDATE listings SET stock=stock-? WHERE id=?',(value,lid))
            db.execute('UPDATE shop_orders SET status=?,paypal_capture=?,updated=? WHERE id=?',('paid_attention_required' if inventory_issue else 'paid',capture_id,now(),order_id))
            # Recorded once in the same transaction as the paid status. This is a
            # platform commission ESTIMATE, not a settled PayPal partner fee.
            db.execute("INSERT OR IGNORE INTO order_finance_events(order_id,event_type,amount,currency,source,created) VALUES(?,?,?,?,?,?)",(order_id,'gross_capture',o['amount'],o['currency'],capture_id,now()))
            db.execute("INSERT OR IGNORE INTO order_finance_events(order_id,event_type,amount,currency,source,created) VALUES(?,?,?,?,?,?)",(order_id,'lapeng_commission_estimate',commission_for(o['amount']),o['currency'],capture_id,now()))
            if fee_value is not None:
                db.execute("INSERT OR IGNORE INTO order_finance_events(order_id,event_type,amount,currency,source,created) VALUES(?,?,?,?,?,?)",
                    (order_id,'paypal_processing_fee_verified',fee_value,o['currency'],capture_id,now()))
            db.execute('DELETE FROM cart_lines WHERE buyer_id=? AND listing_id IN (SELECT listing_id FROM shop_items WHERE order_id=?)',(u['id'],order_id))
        return {'status':'paid_attention_required' if inventory_issue else 'paid','verified':True,'note':'Contact seller: inventory changed during checkout' if inventory_issue else 'Order payment captured in Sandbox'}

    @router.post('/orders/{order_id}/fulfilment')
    def fulfilment(order_id:int,x:StatusIn,u=Depends(current)):
        allowed=['processing','shipped','delivered','completed']
        if x.status not in allowed:raise HTTPException(422,'Invalid fulfilment status')
        with conn() as db:
            o=owned_order(db,order_id,u['id'])
            if o['owner_id']!=u['id']:raise HTTPException(403,'Only the seller can update fulfilment')
            if o['status']!='paid':raise HTTPException(409,'Confirmed payment required before fulfilment')
            forward={'pending':['processing'],'processing':['shipped','completed'],'shipped':['delivered'],'delivered':['completed'],'completed':[]}
            if x.status not in forward.get(o['fulfilment_status'],[]):raise HTTPException(409,'Invalid fulfilment status transition')
            db.execute('UPDATE shop_orders SET fulfilment_status=?,tracking=?,updated=? WHERE id=?',(x.status,x.tracking or o['tracking'],now(),order_id))
        return {'ok':True}

    @router.post('/orders/{order_id}/returns')
    def request_return(order_id:int,x:ReturnIn,u=Depends(current)):
        with conn() as db:
            o=owned_order(db,order_id,u['id'])
            if o['buyer_id']!=u['id']:raise HTTPException(403,'Only buyer can request a return')
            if o['status']!='paid' or o['fulfilment_status'] not in ('shipped','delivered','completed'):raise HTTPException(409,'Return requests require a fulfilled or shipped paid order')
            if fetch(db,"SELECT id FROM shop_returns WHERE order_id=? AND status IN ('requested','approved')",(order_id,)):raise HTTPException(409,'Return request already open')
            rid=db.execute('INSERT INTO shop_returns(order_id,author_id,reason,created,updated) VALUES(?,?,?,?,?)',(order_id,u['id'],x.reason,now(),now())).lastrowid
            return {'id':rid,'status':'requested','note':'Refund not issued; seller review is required'}

    @router.post('/returns/{return_id}/decision')
    def return_decision(return_id:int,x:StatusIn,u=Depends(current)):
        if x.status not in ('approved','declined'):raise HTTPException(422,'Choose approved or declined')
        with conn() as db:
            result=fetch(db,'SELECT r.*,p.owner_id FROM shop_returns r JOIN shop_orders o ON o.id=r.order_id JOIN providers p ON p.id=o.provider_id WHERE r.id=?',(return_id,))
            if not result:raise HTTPException(404,'Return not found')
            if result['owner_id']!=u['id']:raise HTTPException(403,'Only seller can review returns')
            if result['status']!='requested':raise HTTPException(409,'Already reviewed')
            db.execute('UPDATE shop_returns SET status=?,updated=? WHERE id=?',(x.status,now(),return_id))
            return {'status':x.status,'note':'This is not an automated PayPal refund'}

    @router.post('/orders/{order_id}/reviews')
    def item_review(order_id:int,x:dict,u=Depends(current)):
        try: lid=int(x.get('listing_id'));score=int(x.get('score'));txt=str(x.get('text','')).strip()
        except Exception:raise HTTPException(422,'Invalid review')
        if score not in range(1,6) or not 8<=len(txt)<=1000:raise HTTPException(422,'Invalid review details')
        with conn() as db:
            o=owned_order(db,order_id,u['id'])
            if o['buyer_id']!=u['id'] or o['status']!='paid' or o['fulfilment_status'] not in ('delivered','completed'):raise HTTPException(403,'Only a buyer of a delivered, paid order can review')
            if not fetch(db,'SELECT 1 FROM shop_items WHERE order_id=? AND listing_id=?',(order_id,lid)):raise HTTPException(403,'This item was not in your order')
            try:db.execute('INSERT INTO shop_reviews(order_id,listing_id,buyer_id,provider_id,score,text,created) VALUES(?,?,?,?,?,?,?)',(order_id,lid,u['id'],o['provider_id'],score,txt,now()))
            except sqlite3.IntegrityError:raise HTTPException(409,'You have already reviewed this item on this order')
            # Recompute profile ratings across checkout AND prior quotation payments.
            rating=fetch(db,'SELECT AVG(score) avg,COUNT(*) n FROM (SELECT score FROM shop_reviews WHERE provider_id=? UNION ALL SELECT score FROM reviews WHERE provider_id=?)',(o['provider_id'],o['provider_id']))
            db.execute('UPDATE providers SET rating=?,reviews=? WHERE id=?',(rating['avg'] or 0,rating['n'],o['provider_id']))
            return {'ok':True}

    @router.get('/listings/{lid}/reviews')
    def listing_reviews(lid:int):
        with conn() as db:
            a=many(db,'SELECT score,text,created FROM shop_reviews WHERE listing_id=? ORDER BY id DESC LIMIT 30',(lid,))
            b=many(db,'SELECT score,text,created FROM reviews WHERE listing_id=? ORDER BY id DESC LIMIT 30',(lid,))
            all_reviews=sorted(a+b,key=lambda x:x['created'],reverse=True)[:30]
            return {'reviews':all_reviews,'average':round(sum(r['score'] for r in all_reviews)/len(all_reviews),2) if all_reviews else None,'count':len(all_reviews)}

    @router.post('/bookings')
    def booking(x:BookIn,u=Depends(current)):
        if x.ends_at<=x.starts_at or x.ends_at-x.starts_at>86400 or x.starts_at<=now() or x.starts_at>now()+31536000:raise HTTPException(422,'Select a future booking window under 24 hours')
        with conn() as db:
            listing=fetch(db,'SELECT l.*,p.owner_id,p.kind provider_kind,p.remote,p.latitude,p.longitude,p.service_radius_km,p.city,p.country FROM listings l JOIN providers p ON p.id=l.provider_id WHERE l.id=?',(x.listing_id,))
            if not listing or listing['owner_id'] is None:raise HTTPException(404,'Bookable listing not found')
            if not (any(word in listing['kind'].lower() for word in ('service','appointment','lesson','consult','session','tutor','hair','repair','beauty','styling','carpentry')) or 'service' in listing['provider_kind'].lower()):raise HTTPException(422,'Bookings are only available on service listings')
            if listing['owner_id']==u['id']:raise HTTPException(403,'Cannot book your own listing')
            # Local/onsite appointments are never offered as international remote bookings.
            if not listing['remote']:
                if listing['latitude'] is None or listing['longitude'] is None:
                    raise HTTPException(409,'This provider must configure their local service area before accepting appointments')
                if x.buyer_latitude is None or x.buyer_longitude is None:
                    raise HTTPException(422,'Share a location before requesting an on-site appointment')
                from app.main import distance_km
                km=distance_km(x.buyer_latitude,x.buyer_longitude,listing['latitude'],listing['longitude'])
                if km>listing['service_radius_km']:
                    raise HTTPException(422,f'Outside provider service radius ({listing["service_radius_km"]} km). Find a provider nearby or choose an explicitly remote service')

            # Check published opening hours and prohibit simultaneous appointments across all services of a provider.
            from datetime import datetime
            from zoneinfo import ZoneInfo
            sched=fetch(db,'SELECT * FROM provider_schedule WHERE provider_id=?',(listing['provider_id'],))
            if sched:
                tz=ZoneInfo(sched['timezone']); start=datetime.fromtimestamp(x.starts_at,tz); end=datetime.fromtimestamp(x.ends_at,tz)
                hours=json.loads(sched['hours_json']); day=('mon','tue','wed','thu','fri','sat','sun')[start.weekday()]
                rule=hours[day]
                if start.date()!=end.date() or rule.get('closed') or start.strftime('%H:%M')<rule['open'] or end.strftime('%H:%M')>rule['close']:
                    raise HTTPException(422,'Requested time is outside the provider opening hours')
                if x.starts_at<now()+sched['lead_hours']*3600:raise HTTPException(422,'Requested time does not meet the booking notice period')
                if x.ends_at-x.starts_at!=sched['slot_minutes']*60:raise HTTPException(422,'Choose a published appointment duration')
            if fetch(db,"SELECT id FROM service_bookings WHERE provider_id=? AND status IN ('confirmed','requested') AND starts_at<? AND ends_at>?",(listing['provider_id'],x.ends_at,x.starts_at)):raise HTTPException(409,'This provider has an appointment overlapping that time')
            bid=db.execute('INSERT INTO service_bookings(listing_id,buyer_id,provider_id,starts_at,ends_at,note,created) VALUES(?,?,?,?,?,?,?)',(x.listing_id,u['id'],listing['provider_id'],x.starts_at,x.ends_at,x.note,now())).lastrowid
            return {'id':bid,'status':'requested','note':'Provider confirmation required. This is not a paid reservation.'}

    @router.get('/bookings')
    def bookings(u=Depends(current)):
        with conn() as db:return many(db,'SELECT b.*,l.title FROM service_bookings b JOIN listings l ON l.id=b.listing_id JOIN providers p ON p.id=b.provider_id WHERE b.buyer_id=? OR p.owner_id=? ORDER BY b.starts_at DESC',(u['id'],u['id']))

    @router.post('/bookings/{bid}/status')
    def booking_status(bid:int,x:StatusIn,u=Depends(current)):
        if x.status not in ('confirmed','declined','cancelled'):raise HTTPException(422,'Invalid booking status')
        with conn() as db:
            db.execute('BEGIN IMMEDIATE')
            b=fetch(db,'SELECT b.*,p.owner_id FROM service_bookings b JOIN providers p ON p.id=b.provider_id WHERE b.id=?',(bid,))
            if not b:raise HTTPException(404,'Booking not found')
            if x.status in ('confirmed','declined') and b['owner_id']!=u['id']:raise HTTPException(403,'Only provider can confirm or decline')
            if x.status=='cancelled':
                if u['id'] not in (b['buyer_id'],b['owner_id']):
                    raise HTTPException(403,'Only a booking participant can cancel')
                if b['status'] not in ('requested','confirmed'):
                    raise HTTPException(409,'This appointment can no longer be cancelled')
                # A clear, simple prototype policy. Do not claim this handles refunds.
                if b['status']=='confirmed' and u['id']==b['buyer_id'] and b['starts_at']-now()<86400:
                    raise HTTPException(409,'Customer cancellations require at least 24 hours notice. Contact the provider for help.')
                db.execute('UPDATE service_bookings SET status=? WHERE id=?',('cancelled',bid))
                return {'status':'cancelled','payment_note':'Cancellation does not issue any refund. Contact support for paid orders.'}
            if b['status']!='requested':raise HTTPException(409,'Booking is no longer pending')
            if x.status=='confirmed' and fetch(db,"SELECT 1 FROM service_bookings WHERE id!=? AND provider_id=? AND status='confirmed' AND starts_at<? AND ends_at>?",(bid,b['provider_id'],b['ends_at'],b['starts_at'])):raise HTTPException(409,'Time already booked')
            db.execute('UPDATE service_bookings SET status=? WHERE id=?',(x.status,bid))
            return {'status':x.status}

    @router.post('/orders/{order_id}/milestones')
    def add_milestone(order_id:int,x:MilestoneIn,u=Depends(current)):
        with conn() as db:
            o=owned_order(db,order_id,u['id'])
            if o['owner_id']!=u['id']:raise HTTPException(403,'Only provider can add milestones')
            if o['status']!='paid':raise HTTPException(409,'Paid order required')
            if len(many(db,'SELECT id FROM project_milestones WHERE order_id=?',(order_id,)))>=20:raise HTTPException(422,'Milestone limit reached')
            mid=db.execute('INSERT INTO project_milestones(order_id,title,details,due_at,created,updated) VALUES(?,?,?,?,?,?)',(order_id,x.title,x.details,x.due_at,now(),now())).lastrowid
            return {'id':mid,'status':'planned'}

    @router.post('/milestones/{mid}/status')
    def milestone_status(mid:int,x:ProjectUpdateIn,u=Depends(current)):
        with conn() as db:
            m=fetch(db,'SELECT m.*,o.buyer_id,p.owner_id FROM project_milestones m JOIN shop_orders o ON o.id=m.order_id JOIN providers p ON p.id=o.provider_id WHERE m.id=?',(mid,))
            if not m:raise HTTPException(404,'Milestone not found')
            allowed={('planned','submitted'):m['owner_id'],('submitted','approved'):m['buyer_id'],('submitted','changes_requested'):m['buyer_id'],('changes_requested','submitted'):m['owner_id']}
            if (m['status'],x.status) not in allowed:raise HTTPException(409,'Invalid milestone state change')
            if allowed[(m['status'],x.status)]!=u['id']:raise HTTPException(403,'Not authorised for this milestone action')
            db.execute('UPDATE project_milestones SET status=?,updated=? WHERE id=?',(x.status,now(),mid))
            if x.note:db.execute('INSERT INTO order_notes(order_id,actor_id,body,created) VALUES(?,?,?,?)',(m['order_id'],u['id'],x.note,now()))
            return {'status':x.status}

    @router.post('/orders/{order_id}/notes')
    def order_note(order_id:int,x:ProjectUpdateIn,u=Depends(current)):
        with conn() as db:
            owned_order(db,order_id,u['id'])
            if not 1<=len(x.note)<=500:raise HTTPException(422,'Message is required')
            db.execute('INSERT INTO order_notes(order_id,actor_id,body,created) VALUES(?,?,?,?)',(order_id,u['id'],x.note,now()))
        return {'ok':True}

    @router.get('/settlements')
    def settlement_status(u=Depends(current)):
        """Per-currency, participant-only finance views. Never imply escrow or seller payout."""
        with conn() as db:
            merchants=many(db,'SELECT id,name FROM providers WHERE owner_id=?',(u['id'],))
            totals=[]
            for merchant in merchants:
                paid=many(db,"""SELECT id,amount,currency,status,paypal_capture,created
                    FROM shop_orders WHERE provider_id=? AND status IN ('paid','paid_attention_required')
                    ORDER BY id DESC LIMIT 100""",(merchant['id'],))
                fee_rows=many(db,"""SELECT e.order_id,e.amount FROM order_finance_events e
                    JOIN shop_orders o ON o.id=e.order_id WHERE o.provider_id=? AND e.event_type='paypal_processing_fee_verified'""",(merchant['id'],))
                known_fees={f['order_id']:f['amount'] for f in fee_rows}
                grouped={}
                for order in paid:
                    curr=order['currency']; g=grouped.setdefault(curr,{'currency':curr,'gross':0,'lapeng_commission_estimate':0,'provider_before_processor_fees':0,'paypal_fee':0,'paypal_fee_known_orders':0,'seller_paid_out':0,'orders':0})
                    commission=commission_for(order['amount'])
                    g['gross']+=order['amount'];g['lapeng_commission_estimate']+=commission
                    g['provider_before_processor_fees']+=order['amount']-commission;g['orders']+=1
                    if order['id'] in known_fees:
                        g['paypal_fee']+=known_fees[order['id']];g['paypal_fee_known_orders']+=1
                totals.append({'provider_id':merchant['id'],'name':merchant['name'],
                    'by_currency':list(grouped.values()),
                    'orders':[{'id':o['id'],'currency':o['currency'],'gross':o['amount'],
                              'commission_estimate':commission_for(o['amount']),
                              'provider_before_processor_fees':o['amount']-commission_for(o['amount']),
                              'paypal_processing_fee':known_fees.get(o['id']),'payout_status':'not_connected',
                              'attention_required':o['status']=='paid_attention_required'} for o in paid]})
            return {'commission_basis_points':COMMISSION_BPS,'rate_percent':5,
                'paypal_seller_onboarding':'not_connected','seller_payouts':'not_connected',
                'paypal_partner_fees':'not_connected', 'seller_revenue_disbursement':'not_connected',
                'sandbox_platform_receipts':totals,
                'warning':'Illustrative 5% commission. Gross receipts are in LAPENG configured Sandbox merchant. Actual processing fee unknown and seller proceeds have NOT been paid out. No money is held in escrow.'}

    @router.get('/saved')
    def saved(u=Depends(current)):
        with conn() as db:
            data=many(db,"""SELECT l.id,l.title,l.description,l.currency,l.price,p.id provider_id,p.name provider_name
                 FROM saved_listings s JOIN listings l ON l.id=s.listing_id
                 JOIN providers p ON p.id=l.provider_id WHERE s.user_id=? AND p.owner_id IS NOT NULL
                 ORDER BY s.created DESC LIMIT 100""",(u['id'],))
            return data

    @router.post('/saved/{lid}')
    def save_listing(lid:int,u=Depends(current)):
        with conn() as db:
            l=fetch(db,'SELECT l.id,p.owner_id FROM listings l JOIN providers p ON p.id=l.provider_id WHERE l.id=?',(lid,))
            if not l or l['owner_id'] is None:raise HTTPException(404,'Active listing not found')
            if l['owner_id']==u['id']:raise HTTPException(403,'Cannot save your own listing')
            db.execute('INSERT OR IGNORE INTO saved_listings(user_id,listing_id,created) VALUES(?,?,?)',(u['id'],lid,now()))
        return {'saved':True}

    @router.delete('/saved/{lid}')
    def unsave_listing(lid:int,u=Depends(current)):
        with conn() as db:db.execute('DELETE FROM saved_listings WHERE user_id=? AND listing_id=?',(u['id'],lid))
        return {'saved':False}

    app.include_router(router)
