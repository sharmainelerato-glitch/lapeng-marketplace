"""Aftercare permission and lifecycle checks using seeded, synthetic Sandbox state."""
import time
from test_app import client,auth
from app.main import conn

def user(name,email):
    return auth(name,email)

_users=None
def fixture():
    global _users
    if _users is None:
        _users=(user('Aftercare Seller','aftercare-seller@example.test'),
                user('Aftercare Buyer','aftercare-buyer@example.test'),
                user('Aftercare Stranger','aftercare-stranger@example.test'))
    seller,buyer,outsider=_users
    p=client.post('/api/providers',headers=seller,json={'name':'Aftercare Sample Studio','category':'Fashion','kind':'Goods','city':'Cape Town','country':'South Africa','remote':True,'bio':'Realistic example test seller profile for order operations','skills':'retail,clothing','price':20,'capacity':12})
    assert p.status_code==200,p.text
    pid=p.json()['id']
    l=client.post(f'/api/providers/{pid}/listings',headers=seller,json={'title':'Test cotton dress','description':'Simple garment for aftercare tests','kind':'Goods','price':20,'stock':10,'currency':'USD'})
    assert l.status_code==200,l.text
    lid=l.json()['id']
    uid=client.get('/api/me',headers=buyer).json()['id']
    with conn() as db:
        oid=db.execute("INSERT INTO shop_orders(buyer_id,provider_id,amount,currency,status,fulfilment_status,paypal_capture,created,updated) VALUES(?, ?, 20, 'USD','paid','delivered','CAPTURE_SYNTHETIC_ONLY',?,?)",(uid,pid,int(time.time()),int(time.time()))).lastrowid
        db.execute('INSERT INTO shop_items(order_id,listing_id,title,choice,qty,unit_price) VALUES(?,?,?,?,?,?)',(oid,lid,'Test cotton dress','M',1,20))
    return seller,buyer,outsider,oid,lid,pid

def test_receipt_and_order_privacy():
    seller,buyer,outsider,oid,lid,pid=fixture()
    url=f'/api/aftercare/orders/{oid}/receipt'
    assert client.get(url,headers=outsider).status_code==403
    assert client.get(url,headers=buyer).json()['type'].startswith('Sandbox')
    assert client.get(url,headers=seller).status_code==200
    assert client.get(f'/api/aftercare/orders/{oid}',headers=outsider).status_code==403

def test_cases_permissions_and_replay():
    seller,buyer,outsider,oid,lid,pid=fixture()
    path=f'/api/aftercare/orders/{oid}/cases'
    data={'kind':'exchange','reason':'I need a different dress size','listing_id':lid,'replacement_option':'L'}
    assert client.post(path,headers=outsider,json=data).status_code==403
    res=client.post(path,headers=buyer,json=data)
    assert res.status_code==200,res.text
    cid=res.json()['id']
    assert client.post(path,headers=buyer,json=data).status_code==409
    endpoint=f'/api/aftercare/cases/{cid}/decision'
    assert client.post(endpoint,headers=buyer,json={'decision':'approved'}).status_code==403
    assert client.post(endpoint,headers=outsider,json={'decision':'approved'}).status_code==403
    assert client.post(endpoint,headers=seller,json={'decision':'approved','note':'Bring the item back first'}).status_code==200
    assert client.post(endpoint,headers=seller,json={'decision':'declined'}).status_code==409
    info=client.get(f'/api/aftercare/orders/{oid}',headers=buyer).json()
    assert info['cases'][0]['status']=='approved'

def test_tracking_owner_only():
    seller,buyer,outsider,oid,lid,pid=fixture()
    url=f'/api/aftercare/orders/{oid}/tracking'
    data={'status':'in_transit','carrier':'Test Carrier','tracking_ref':'REF-1234','note':'Synthetic scan'}
    assert client.post(url,headers=buyer,json=data).status_code==403
    assert client.post(url,headers=outsider,json=data).status_code==403
    assert client.post(url,headers=seller,json={**data,'tracking_ref':''}).status_code==422
    assert client.post(url,headers=seller,json=data).status_code==200
    assert client.get(f'/api/aftercare/orders/{oid}',headers=buyer).json()['events'][0]['carrier']=='Test Carrier'

def test_mutually_approved_booking_reschedule():
    seller,buyer,outsider,oid,lid,pid=fixture()
    now=int(time.time())
    with conn() as db:
        bid=db.execute("INSERT INTO service_bookings(listing_id,buyer_id,provider_id,starts_at,ends_at,note,status,created) VALUES(?,?,?,?,?,'appointment','confirmed',?)",(lid,client.get('/api/me',headers=buyer).json()['id'],pid,now+7*86400,now+7*86400+3600,now)).lastrowid
    path=f'/api/aftercare/bookings/{bid}/reschedules'
    target=now+8*86400
    req=client.post(path,headers=buyer,json={'starts_at':target,'ends_at':target+3600,'reason':'Need another day'})
    assert req.status_code==200,req.text
    rid=req.json()['id']
    assert client.post(f'/api/aftercare/reschedules/{rid}/decision',headers=buyer,json={'decision':'approved'}).status_code==403
    assert client.post(f'/api/aftercare/reschedules/{rid}/decision',headers=outsider,json={'decision':'approved'}).status_code==403
    with conn() as db:assert db.execute('SELECT starts_at FROM service_bookings WHERE id=?',(bid,)).fetchone()[0]!=target
    assert client.post(f'/api/aftercare/reschedules/{rid}/decision',headers=seller,json={'decision':'approved'}).status_code==200
    with conn() as db:assert db.execute('SELECT starts_at FROM service_bookings WHERE id=?',(bid,)).fetchone()[0]==target
    assert client.post(f'/api/aftercare/reschedules/{rid}/decision',headers=seller,json={'decision':'approved'}).status_code==409
