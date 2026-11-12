"""Security regression checks. No PayPal credentials or external network required."""
from test_app import client, auth

def test_security_headers_and_origin():
    r=client.get('/')
    assert 'Content-Security-Policy' in r.headers
    assert r.headers['X-Frame-Options']=='DENY'
    assert r.headers['X-Content-Type-Options']=='nosniff'
    assert client.post('/api/auth/login',headers={'Origin':'https://hostile.example'},json={'email':'a@b.co','password':'irrelevant'}).status_code==403
    assert client.post('/api/auth/register',data='X'*65537,headers={'Content-Type':'application/json'}).status_code==413

def test_logout_revokes_session():
    h=auth('Logout Test','logout@lapeng.test')
    assert client.get('/api/me',headers=h).status_code==200
    assert client.post('/api/auth/logout',headers=h).status_code==200
    assert client.get('/api/me',headers=h).status_code==401

def test_quote_confidentiality_and_guardian_access():
    buyer=auth('Privacy Buyer','privatebuyer@lapeng.test')
    seller=auth('Privacy Seller','privateseller@lapeng.test')
    stranger=auth('Privacy Stranger','privatestranger@lapeng.test')
    p=client.post('/api/providers',headers=seller,json={'name':'Private Dev','category':'Web development','city':'Cape Town','country':'South Africa','bio':'Private independent web development services','skills':'website,react','price':150,'capacity':10}).json()['id']
    r=client.post('/api/requests',headers=buyer,json={'title':'A private website request','description':'Build a responsive website for a new community workshop','budget':2000,'quantity':1}).json()['id']
    q=client.post(f'/api/requests/{r}/proposals',headers=seller,json={'provider_id':p,'amount':1425,'note':'Private negotiated quote'}).json()['id']
    outsider=client.get(f'/api/requests/{r}',headers=stranger).json()
    assert outsider['proposals']==[]
    assert outsider['messages']==[]
    assert outsider['buyer_id'] is None
    assert len(client.get(f'/api/requests/{r}',headers=buyer).json()['proposals'])==1
    assert len(client.get(f'/api/requests/{r}',headers=seller).json()['proposals'])==1
    assert client.post(f'/api/ai/guardian/{r}',headers=stranger).status_code==403
    assert client.post(f'/api/ai/assemble/{r}',headers=stranger).status_code==403
    assert client.post(f'/api/proposals/{q}/accept',headers=buyer).status_code==200
    assert client.post(f'/api/requests/{r}/proposals',headers=seller,json={'provider_id':p,'amount':900,'note':'Late second quote'}).status_code==409

def test_report_target_exists():
    h=auth('Reporter','reporter@lapeng.test')
    assert client.post('/api/reports',headers=h,json={'target_type':'provider','target_id':999999999,'reason':'Need someone to investigate this listing'}).status_code==404
