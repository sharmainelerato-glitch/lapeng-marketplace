import time
from test_app import client,auth
from app.main import distance_km

SELLER={'name':'Crown and Curl Atelier','category':'Hair & beauty','kind':'Local services',
        'city':'Johannesburg','country':'South Africa','remote':False,
        'bio':'Natural hair styling, braids and special occasions at our salon.',
        'skills':'braids,styling,colour','price':25,'capacity':4,
        'website':'https://example.org/salon','latitude':-26.2041,'longitude':28.0473,'service_radius_km':30}

def test_location_contract_and_site():
    assert distance_km(-26.2041,28.0473,51.5072,-0.1276)>9000
    assert client.get('/').headers['permissions-policy'].find('geolocation=(self)')!=-1
    seller=auth('Curl Seller','seller-curl@example.org')
    bad=SELLER|{'website':'javascript:alert(1)'}
    assert client.post('/api/providers',headers=seller,json=bad).status_code==422
    bad=SELLER|{'latitude':None,'longitude':None}
    assert client.post('/api/providers',headers=seller,json=bad).status_code==422
    pr=client.post('/api/providers',headers=seller,json=SELLER)
    assert pr.status_code==200,pr.text
    pid=pr.json()['id']
    profile=client.get('/api/providers/'+str(pid)).json()
    assert profile['website']=='https://example.org/salon'
    assert profile['service_radius_km']==30
    assert client.get('/api/providers',params={'latitude':-26.20,'longitude':28.05,'nearby':'true'}).status_code==200
    near=client.get('/api/providers',params={'latitude':-26.20,'longitude':28.05,'nearby':'true'}).json()
    assert any(x['id']==pid and x['distance_km']<5 for x in near)
    far=client.get('/api/providers',params={'latitude':51.5072,'longitude':-0.1276,'nearby':'true'}).json()
    assert not any(x['id']==pid for x in far)
    assert client.get('/api/providers',params={'latitude':120,'longitude':0,'nearby':'true'}).status_code==422


def test_local_booking_rejects_distant_and_missing_location():
    seller=client.post('/api/auth/login',json={'email':'seller-curl@example.org','password':'correct-horse-battery-89'}).json()
    sh={'Authorization':'Bearer '+seller['token']}
    buyer=auth('Curl Buyer','buyer-curl@example.org')
    profiles=client.get('/api/me',headers=sh).json()['businesses']
    pid=next(p['id'] for p in profiles if p['name']=='Crown and Curl Atelier')
    listing=client.post('/api/providers/'+str(pid)+'/listings',headers=sh,json={'title':'Hair styling appointment','description':'Professional haircut and braided styling session.','price':25,'kind':'Services','stock':5})
    assert listing.status_code==200,listing.text
    lid=listing.json()['id']
    params={'listing_id':lid,'starts_at':int(time.time())+86400,'ends_at':int(time.time())+90000,'note':'Trim and colour'}
    assert client.post('/api/commerce/bookings',headers=buyer,json=params).status_code==422
    distant=client.post('/api/commerce/bookings',headers=buyer,json=params|{'buyer_latitude':51.5072,'buyer_longitude':-0.1276})
    assert distant.status_code==422,distant.text
    near=client.post('/api/commerce/bookings',headers=buyer,json=params|{'buyer_latitude':-26.205,'buyer_longitude':28.04})
    assert near.status_code==200,near.text
    cart=client.post('/api/commerce/cart',headers=buyer,json={'listing_id':lid,'quantity':1})
    assert cart.status_code==200,cart.text
    # PayPal is not configured during tests; checkout must still require PayPal and never claim paid.
