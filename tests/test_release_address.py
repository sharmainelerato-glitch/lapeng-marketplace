"""Buyer address book and server-side shipping cutoff regression tests."""
import time
from test_app import client,auth
from app.main import conn


def test_saved_address_is_private_and_reusable():
    a=auth('Address Buyer A','address_a@lapeng.test')
    b=auth('Address Buyer B','address_b@lapeng.test')
    assert client.get('/api/commerce/delivery-address',headers=a).json() is None
    data={'delivery_address':'12 Market Road, Unit 4, Johannesburg 2000','delivery_country':'South Africa'}
    assert client.put('/api/commerce/delivery-address',headers=a,json=data).status_code==200
    assert client.get('/api/commerce/delivery-address',headers=a).json()['delivery_address']==data['delivery_address']
    assert client.get('/api/commerce/delivery-address',headers=b).json() is None
    assert client.put('/api/commerce/delivery-address',headers=a,json={**data,'delivery_address':'short'}).status_code==422
    assert client.get('/api/commerce/delivery-address').status_code==401


def test_order_address_edit_before_shipping_only():
    buyer=auth('Address Order Buyer','address_order_buyer@lapeng.test')
    stranger=auth('Address Order Stranger','address_order_stranger@lapeng.test')
    provider_owner=auth('Address Order Seller','address_order_seller@lapeng.test')
    seller=client.post('/api/providers',headers=provider_owner,json={
        'name':'Address Test Goods','category':'Fashion','kind':'Goods','city':'Cape Town',
        'country':'South Africa','remote':True,'bio':'Small products and accessories boutique',
        'skills':'design,retail','price':25,'capacity':5})
    assert seller.status_code==200,seller.text
    with conn() as db:
        bid=client.get('/api/me',headers=buyer).json()['id']
        oid=db.execute('INSERT INTO shop_orders(buyer_id,provider_id,amount,currency,delivery_address,status,created,updated) VALUES(?,?,?,?,?,?,?,?)',
            (bid,seller.json()['id'],25,'USD','Old delivery address','paid',int(time.time()),int(time.time()))).lastrowid
    url=f'/api/commerce/orders/{oid}/delivery-address'
    payload={'delivery_address':'45 New Street, Cape Town 8001'}
    assert client.patch(url,headers=stranger,json=payload).status_code==403
    assert client.patch(url,headers=provider_owner,json=payload).status_code==403
    assert client.patch(url,headers=buyer,json=payload).status_code==200
    with conn() as db:
        db.execute("UPDATE shop_orders SET fulfilment_status='shipped' WHERE id=?",(oid,))
    assert client.patch(url,headers=buyer,json={'delivery_address':'99 Fake Road, Cape Town 8001'}).status_code==409
    assert client.get(f'/api/commerce/orders/{oid}',headers=buyer).json()['delivery_address']==payload['delivery_address']
