"""Opportunity AI flow: real matching, human approvals, permissions and geography.
Run separately to avoid test_app.py's shared registration throttle fixture.
"""
import os
import tempfile
from pathlib import Path

# Use an isolated file before app import.
_tmp = tempfile.TemporaryDirectory()
os.environ['LAPENG_DB'] = str(Path(_tmp.name) / 'lapeng.sqlite3')
os.environ['LAPENG_DEMO_DATA'] = '0'
os.environ.pop('AI_API_KEY', None)
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def account(name):
    res=client.post('/api/auth/register',json={'name':name,'email':f'{name}@lapeng.test','password':'correct-horse-battery-89'})
    assert res.status_code==200,res.text
    return {'Authorization':'Bearer '+res.json()['token']}

def setup_module(module):
    global seller,buyer,other,listing,part,plan
    seller,buyer,other=account('sellerop'),account('buyerop'),account('strangerop')
    p=client.post('/api/providers',headers=seller,json={'name':'Johannesburg Cakes','category':'Food & bakery',
        'kind':'service','city':'Johannesburg','country':'South Africa','remote':False,
        'bio':'Handmade birthday cakes and bakery catering','skills':'cake, birthday, baking',
        'price':200,'capacity':6,'latitude':-26.20,'longitude':28.04,'service_radius_km':25})
    assert p.status_code==200,p.text
    r=client.post(f'/api/providers/{p.json()["id"]}/listings',headers=seller,json={'title':'Birthday cake for celebration',
        'description':'Custom cake for birthday party','price':200,'currency':'ZAR','kind':'service','stock':6})
    assert r.status_code==200,r.text
    listing=r.json()['id']
    response=client.post('/api/opportunities/plans',headers=buyer,json={'need':'Please get me a birthday cake for a celebration',
        'parts':['birthday cake'],'city':'Johannesburg','country':'South Africa','currency':'ZAR',
        'latitude':-26.21,'longitude':28.03,'budget':1000})
    assert response.status_code==200,response.text
    plan=response.json()['id'];part=response.json()['parts'][0]['id']

def test_matching_only_real_and_geo_filtered():
    res=client.get(f'/api/opportunities/plans/{plan}',headers=buyer)
    assert res.status_code==200
    assert any(x['listing_id']==listing for x in res.json()['parts'][0]['suggestions'])
    england=client.post('/api/opportunities/plans',headers=buyer,json={'need':'Please get a birthday cake delivered in London',
        'parts':['birthday cake'],'city':'London','country':'United Kingdom'})
    assert england.status_code==200
    assert england.json()['parts'][0]['suggestions']==[]

def test_private_plan_and_provider_invitation():
    assert client.get(f'/api/opportunities/plans/{plan}',headers=other).status_code==403
    assert client.post(f'/api/opportunities/plans/{plan}/parts/{part}/choose',headers=other,json={'listing_id':listing}).status_code==403
    assert client.get('/api/opportunities/invitations',headers=other).json()==[]
    chosen=client.post(f'/api/opportunities/plans/{plan}/parts/{part}/choose',headers=buyer,json={'listing_id':listing})
    assert chosen.status_code==200,chosen.text
    assert chosen.json()['status']=='invited'
    assert client.post(f'/api/opportunities/invitations/{part}/respond',headers=other,json={'accept':True}).status_code==404
    assert client.get('/api/opportunities/invitations',headers=seller).json()[0]['part_id']==part
    assert client.get(f'/api/opportunities/plans/{plan}/payment-readiness',headers=buyer).json()['eligible_interests']==[]
    accepted=client.post(f'/api/opportunities/invitations/{part}/respond',headers=seller,json={'accept':True,'note':'Happy to discuss'})
    assert accepted.status_code==200,accepted.text
    ready=client.get(f'/api/opportunities/plans/{plan}/payment-readiness',headers=buyer).json()
    assert ready['eligible_interests'][0]['listing_id']==listing
    assert 'separately per seller' in ready['note']

def test_no_duplicate_invitation_and_no_fabricated_payment():
    response=client.post(f'/api/opportunities/plans/{plan}/parts/{part}/choose',headers=buyer,json={'listing_id':listing})
    assert response.status_code==409
    assert client.post(f'/api/opportunities/invitations/{part}/respond',headers=seller,json={'accept':True}).status_code==409
    response=client.get(f'/api/opportunities/plans/{plan}',headers=buyer)
    assert response.json()['parts'][0]['provider_decision']=='accepted'
    assert 'No provider is booked or paid' in response.json()['note']
