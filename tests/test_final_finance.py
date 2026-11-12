"""Final milestone: honest commission arithmetic, saved-listing permissions and payment guards.
Run after test_app.py when using the shared test fixture database.
"""
import time
from test_app import client, auth
from app.main import conn


def test_saved_listing_is_user_owned_and_demo_cannot_be_bookmarked():
    owner=auth('Release Provider','release-provider@lapeng.test')
    buyer=auth('Release Buyer','release-buyer@lapeng.test')
    other=auth('Release Other','release-other@lapeng.test')
    provider=client.post('/api/providers',headers=owner,json={
        'name':'Release Goods Studio','category':'Home & furniture','kind':'Goods',
        'city':'Johannesburg','country':'South Africa','remote':True,
        'bio':'Custom goods created with care in our workshop',
        'skills':'crafts,design','price':35,'capacity':12})
    assert provider.status_code==200,provider.text
    listing=client.post('/api/providers/'+str(provider.json()['id'])+'/listings',headers=owner,json={
        'title':'Release test table','description':'Solid wooden side table, matte finish',
        'kind':'Goods','stock':5,'price':35,'currency':'USD'})
    assert listing.status_code==200,listing.text
    lid=listing.json()['id']
    assert client.post('/api/commerce/saved/'+str(lid)).status_code==401
    assert client.post('/api/commerce/saved/'+str(lid),headers=owner).status_code==403
    assert client.post('/api/commerce/saved/'+str(lid),headers=buyer).status_code==200
    assert client.post('/api/commerce/saved/'+str(lid),headers=buyer).status_code==200
    assert len(client.get('/api/commerce/saved',headers=buyer).json())==1
    assert not client.get('/api/commerce/saved',headers=other).json()
    assert client.delete('/api/commerce/saved/'+str(lid),headers=other).status_code==200
    assert len(client.get('/api/commerce/saved',headers=buyer).json())==1
    assert client.delete('/api/listings/'+str(lid),headers=owner).status_code==200
    assert client.get('/api/commerce/saved',headers=buyer).json()==[]


def test_commission_and_seller_payouts_not_falsely_reported():
    seller={'Authorization':'Bearer '+client.post('/api/auth/login',json={'email':'seller@example.org','password':'correct-horse-battery-89'}).json()['token']}
    buyer={'Authorization':'Bearer '+client.post('/api/auth/login',json={'email':'buyer@example.org','password':'correct-horse-battery-89'}).json()['token']}
    seller_id=client.get('/api/me',headers=seller).json()['id']
    buyer_id=client.get('/api/me',headers=buyer).json()['id']
    provider=client.post('/api/providers',headers=seller,json={
        'name':'Finance Craft Studio','category':'Fashion','kind':'Goods',
        'city':'Cape Town','country':'South Africa','remote':True,
        'bio':'Handmade clothing and other wearable accessories',
        'skills':'fashion,tailoring','price':35,'capacity':7}).json()['id']
    # Seed only a test fixture representing a previously verified Sandbox capture.
    with conn() as db:
        db.execute("INSERT INTO shop_orders(buyer_id,provider_id,amount,currency,status,paypal_capture,created,updated) VALUES(?,?,35,'USD','paid','CAPTURE_TEST_123',?,?)",
            (buyer_id,provider,int(time.time()),int(time.time())))
    response=client.get('/api/commerce/settlements',headers=seller)
    assert response.status_code==200,response.text
    data=response.json()
    line=next(x for x in data['sandbox_platform_receipts'] if x['provider_id']==provider)['by_currency'][0]
    assert line['gross']==35
    assert line['lapeng_commission_estimate']==1.75
    assert line['provider_before_processor_fees']==33.25
    assert line['seller_paid_out']==0
    assert data['seller_payouts']=='not_connected'
    assert client.get('/api/commerce/settlements',headers=buyer).json()['sandbox_platform_receipts']==[]


def test_paypal_webhook_disabled_without_secret_and_refund_needs_moderator():
    buyer={'Authorization':'Bearer '+client.post('/api/auth/login',json={'email':'buyer@example.org','password':'correct-horse-battery-89'}).json()['token']}
    assert client.post('/api/paypal-ops/webhook',json={'id':'X','event_type':'PAYMENT.CAPTURE.COMPLETED'}).status_code==503
    assert client.post('/api/paypal-ops/orders/1/refund',headers=buyer).status_code==403
    assert client.get('/api/paypal-ops/orders/999999/refund-status',headers=buyer).status_code==404


def test_confirmed_booking_can_cancel_in_time_but_not_after_cutoff():
    seller={'Authorization':'Bearer '+client.post('/api/auth/login',json={'email':'seller@example.org','password':'correct-horse-battery-89'}).json()['token']}
    buyer={'Authorization':'Bearer '+client.post('/api/auth/login',json={'email':'buyer@example.org','password':'correct-horse-battery-89'}).json()['token']}
    seller_uid=client.get('/api/me',headers=seller).json()['id']
    with conn() as db:
        provider=db.execute('SELECT id FROM providers WHERE owner_id=? AND remote=0 ORDER BY id LIMIT 1',(seller_uid,)).fetchone()
        assert provider
        lid=db.execute("INSERT INTO listings(provider_id,title,description,price,kind,stock,currency) VALUES(?,?,?,?,?,?,?)",
            (provider['id'],'Booking cancellation test','Carpentry appointment including furniture advice',40,'service',20,'USD')).lastrowid
        future=int(time.time())+72*3600
        bid=db.execute('INSERT INTO service_bookings(listing_id,buyer_id,provider_id,starts_at,ends_at,note,status,created) VALUES(?,?,?,?,?,?,?,?)',
            (lid,client.get('/api/me',headers=buyer).json()['id'],provider['id'],future,future+3600,'Test','confirmed',int(time.time()))).lastrowid
    r=client.post(f'/api/commerce/bookings/{bid}/status',headers=buyer,json={'status':'cancelled'})
    assert r.status_code==200,r.text
    assert r.json()['status']=='cancelled'
    with conn() as db:
        late=int(time.time())+3600
        bid2=db.execute('INSERT INTO service_bookings(listing_id,buyer_id,provider_id,starts_at,ends_at,note,status,created) VALUES(?,?,?,?,?,?,?,?)',
            (lid,client.get('/api/me',headers=buyer).json()['id'],provider['id'],late,late+3600,'Test','confirmed',int(time.time()))).lastrowid
    assert client.post(f'/api/commerce/bookings/{bid2}/status',headers=buyer,json={'status':'cancelled'}).status_code==409
    assert client.post(f'/api/commerce/bookings/{bid2}/status',headers=seller,json={'status':'cancelled'}).status_code==200
