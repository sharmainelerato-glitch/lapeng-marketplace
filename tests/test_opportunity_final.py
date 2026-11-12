"""Tests of comparison, declines, recovery and paid-order evidence with isolated mock DB records.
Payment fixtures are simulated captured records, NOT a genuine PayPal payment.
"""
import os,tempfile
from pathlib import Path
_tmp=tempfile.TemporaryDirectory()
os.environ['LAPENG_DB']=str(Path(_tmp.name)/'test.sqlite3')
os.environ['LAPENG_DEMO_DATA']='0'
os.environ.pop('AI_API_KEY',None)
from fastapi.testclient import TestClient
from app.main import app,conn
client=TestClient(app)

def acc(w):
 r=client.post('/api/auth/register',json={'name':w,'email':w+'@example.test','password':'strong-test-password-123'})
 assert r.status_code==200,r.text
 return {'Authorization':'Bearer '+r.json()['token']},r.json()['user']['id']

def setup_module(module):
 global buyer,seller1,seller2,outsider,listing1,listing2,plan,part,buyer_id,listing3
 buyer,buyer_id=acc('opbuyerfinal')
 seller1,s1=acc('sellerfinala');seller2,s2=acc('sellerfinalb');outsider,_=acc('outsiderfinal')
 def listing(auth,who,price):
  r=client.post('/api/providers',headers=auth,json={'name':who,'category':'Food & bakery','kind':'service','city':'Johannesburg','country':'South Africa','remote':False,'bio':'Local custom birthday cakes and party baking','skills':'birthday cakes baking','price':price,'capacity':8,'latitude':-26.2,'longitude':28.0,'service_radius_km':45})
  assert r.status_code==200,r.text
  x=client.post('/api/providers/'+str(r.json()['id'])+'/listings',headers=auth,json={'title':'Birthday cake for party '+who,'description':'Made to order birthday cake','price':price,'currency':'USD','kind':'service','stock':8})
  assert x.status_code==200,x.text
  return x.json()['id'],r.json()['id']
 listing1,p1=listing(seller1,'Bakery A',35)
 listing2,p2=listing(seller2,'Bakery B',45)
 r=client.post('/api/opportunities/plans',headers=buyer,json={'need':'Please help me find a birthday cake for my party','parts':['birthday cake'],'city':'Johannesburg','country':'South Africa','currency':'USD','budget':100,'latitude':-26.2,'longitude':28.0})
 assert r.status_code==200,r.text
 plan=r.json()['id'];part=r.json()['parts'][0]['id']

def test_compare_private_and_evidence_empty():
 assert client.get(f'/api/opportunities/plans/{plan}/compare',headers=outsider).status_code==403
 assert client.get(f'/api/opportunities/plans/{plan}/evidence',headers=outsider).status_code==403
 c=client.get(f'/api/opportunities/plans/{plan}/compare',headers=buyer)
 assert c.status_code==200,c.text
 assert len(c.json()['scenarios'])==2
 assert len(c.json()['scenarios'][0]['picks'])==1
 assert c.json()['scenarios'][0]['budget_status']=='Within stated budget'
 assert c.json()['scenarios'][0]['picks'][0]['listing_id']==listing1
 assert client.get(f'/api/opportunities/plans/{plan}/evidence',headers=buyer).json()['paid_orders']==0

def test_recovery_requires_decline_and_buyer_reapproval():
 assert client.post(f'/api/opportunities/plans/{plan}/parts/{part}/recover',headers=buyer).status_code==409
 assert client.post(f'/api/opportunities/plans/{plan}/parts/{part}/choose',headers=buyer,json={'listing_id':listing1}).status_code==200
 assert client.post(f'/api/opportunities/plans/{plan}/parts/{part}/recover',headers=buyer).status_code==409
 assert client.post(f'/api/opportunities/invitations/{part}/respond',headers=seller1,json={'accept':False,'note':'Unavailable'}).status_code==200
 assert client.post(f'/api/opportunities/plans/{plan}/parts/{part}/recover',headers=outsider).status_code==403
 r=client.post(f'/api/opportunities/plans/{plan}/parts/{part}/recover',headers=buyer)
 assert r.status_code==200,r.text
 assert any(x['listing_id']==listing2 for x in r.json()['alternatives'])
 fresh=client.get(f'/api/opportunities/plans/{plan}',headers=buyer).json()['parts'][0]
 assert fresh['provider_decision']=='not_invited' and fresh['buyer_approved']==0
 assert client.post(f'/api/opportunities/plans/{plan}/parts/{part}/choose',headers=buyer,json={'listing_id':listing2}).status_code==200
 assert client.post(f'/api/opportunities/invitations/{part}/respond',headers=seller2,json={'accept':True}).status_code==200

def test_evidence_rejects_unpaid_wrong_item_and_other_buyer():
 # Insert actual-shaped rows with mock statuses into isolated DB, not a payment processor.
 with conn() as db:
  pid=db.execute('SELECT provider_id FROM listings WHERE id=?',(listing2,)).fetchone()['provider_id']
  unpaid=db.execute('INSERT INTO shop_orders(buyer_id,provider_id,amount,currency,created,updated) VALUES(?,?,?,?,?,?)',(buyer_id,pid,45,'USD',1,1)).lastrowid
  paid_wrong=db.execute("INSERT INTO shop_orders(buyer_id,provider_id,amount,currency,status,paypal_capture,created,updated) VALUES(?,?,?,?,?,?,?,?)",(buyer_id,pid,30,'USD','paid','MOCK-CAPTURE-TEST',1,1)).lastrowid
  db.execute('INSERT INTO shop_items(order_id,listing_id,title,qty,unit_price) VALUES(?,?,?,?,?)',(paid_wrong,listing1,'wrong',1,30))
  paid_right=db.execute("INSERT INTO shop_orders(buyer_id,provider_id,amount,currency,status,paypal_capture,created,updated) VALUES(?,?,?,?,?,?,?,?)",(buyer_id,pid,45,'USD','paid','MOCK-CAPTURE-RIGHT',1,1)).lastrowid
  db.execute('INSERT INTO shop_items(order_id,listing_id,title,qty,unit_price) VALUES(?,?,?,?,?)',(paid_right,listing2,'correct',1,45))
 for number,expected in [(unpaid,409),(paid_wrong,422)]:
  r=client.post(f'/api/opportunities/plans/{plan}/parts/{part}/link-order',headers=buyer,json={'order_id':number})
  assert r.status_code==expected,r.text
 assert client.post(f'/api/opportunities/plans/{plan}/parts/{part}/link-order',headers=outsider,json={'order_id':paid_right}).status_code==403
 good=client.post(f'/api/opportunities/plans/{plan}/parts/{part}/link-order',headers=buyer,json={'order_id':paid_right})
 assert good.status_code==200,good.text
 # Repeat linking is idempotent.
 assert client.post(f'/api/opportunities/plans/{plan}/parts/{part}/link-order',headers=buyer,json={'order_id':paid_right}).status_code==200
 proof=client.get(f'/api/opportunities/plans/{plan}/evidence',headers=buyer).json()
 assert proof['paid_orders']==1 and len(proof['verified_order_links'])==1
 assert any(x['event']=='verified_paypal_order_linked' for x in proof['events'])
 assert client.post(f'/api/opportunities/plans/{plan}/parts/{part}/choose',headers=buyer,json={'listing_id':listing1}).status_code==409
