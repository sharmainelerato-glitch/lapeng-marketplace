import os, tempfile
from pathlib import Path
DB_PATH=Path(tempfile.gettempdir())/'lapeng_pytest_unique.sqlite3'
if DB_PATH.exists():DB_PATH.unlink()
os.environ['LAPENG_DB']=str(DB_PATH)
from fastapi.testclient import TestClient
from app.main import app,assemble,candidate_score
client=TestClient(app)

def auth(name,email):
    res=client.post('/api/auth/register',json={'name':name,'email':email,'password':'correct-horse-battery-89'})
    assert res.status_code==200,res.text
    return {'Authorization':'Bearer '+res.json()['token']}

def test_health_and_seeding():
    assert client.get('/health').json()['ok']
    assert len(client.get('/api/providers').json())>=6
    assert client.get('/static/favicon.svg').status_code==200
    assert client.get('/').status_code==200

def test_auth_isolation_quote_and_approval():
    buyer=auth('Buyer Test','buyer@example.org')
    seller=auth('Provider Test','seller@example.org')
    other=auth('Other Member','other@example.org')
    pr=client.post('/api/providers',headers=seller,json={'name':'Tester Wood Studio','category':'Carpentry','kind':'Services','city':'Johannesburg','country':'South Africa','remote':False,'bio':'Carpentry and quality handmade furniture for homes.','skills':'woodworking,cabinetry','price':125,'capacity':9})
    assert pr.status_code==200,pr.text
    pid=pr.json()['id']
    rq=client.post('/api/requests',headers=buyer,json={'title':'Build my new cupboard','description':'Need a sturdy wooden cupboard for our living room.','category':'Carpentry','budget':1000,'quantity':2,'city':'Johannesburg','remote':False})
    assert rq.status_code==200,rq.text
    rid=rq.json()['id']
    assert client.post(f'/api/requests/{rid}/proposals',headers=other,json={'provider_id':pid,'amount':150,'note':'Can do'}).status_code==403
    quote=client.post(f'/api/requests/{rid}/proposals',headers=seller,json={'provider_id':pid,'amount':260,'note':'Two cabinets, delivery discussed separately'})
    assert quote.status_code==200,quote.text
    qid=quote.json()['id']
    assert client.post(f'/api/proposals/{qid}/accept',headers=other).status_code==403
    assert client.post(f'/api/proposals/{qid}/accept',headers=buyer).status_code==200
    assert client.post(f'/api/proposals/{qid}/accept',headers=buyer).status_code==409
    assert client.post(f'/api/requests/{rid}/messages',headers=other,json={'body':'Should not be allowed'}).status_code==403
    assert client.post(f'/api/requests/{rid}/messages',headers=buyer,json={'body':'Could you send examples?'}).status_code==200
    assert client.post(f'/api/requests/{rid}/messages',headers=seller,json={'body':'Of course!'}).status_code==200
    assert client.get(f'/api/requests/{rid}',headers=other).json()['messages']==[]
    assert len(client.get(f'/api/requests/{rid}',headers=buyer).json()['messages'])==2
    assert client.post('/api/reviews',headers=buyer,json={'payment_id':123,'score':5,'text':'Great work and on time'}).status_code==403
    assert client.post(f'/api/paypal/create/{qid}',headers=other).status_code==403
    assert client.post(f'/api/paypal/create/{qid}',headers=buyer).status_code==503

def test_guardian_and_coalition():
    buyer=client.post('/api/auth/login',json={'email':'buyer@example.org','password':'correct-horse-battery-89'}).json()
    head={'Authorization':'Bearer '+buyer['token']}
    rid=1
    out=client.post(f'/api/ai/assemble/{rid}',headers=head)
    assert out.status_code==200,out.text
    result=out.json()
    assert result['requested_units']==2
    assert result['covered_units']+result['missing_units']==2
    assert result['assistant']['mode']=='rules_only'
    report=client.post('/api/reports',headers=head,json={'target_type':'provider','target_id':1,'reason':'Potentially copied photos in profile.'})
    assert report.status_code==200,report.text
    assert client.get('/api/reports',headers=head).json()[0]['status']=='open'
    assert client.post('/api/reports',headers=head,json={'target_type':'unrecognized','target_id':1,'reason':'Unclear provider information.'}).status_code==400
