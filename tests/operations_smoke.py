"""Run with LAPENG_DB pointed to a disposable database (never the user database)."""
from fastapi.testclient import TestClient
from app.main import app
import datetime, json
c=TestClient(app)
def ok(r):
 assert r.status_code<300,(r.status_code,r.text[:500]);return r.json()
def signup(email):
 x=ok(c.post('/api/auth/register',json={'email':email,'name':'Test Person','password':'GoodPassword#4271'}))
 return {'Authorization':'Bearer '+x['token']}
seller=signup('provider-smoke@example.test');buyer=signup('buyer-smoke@example.test')
p=ok(c.post('/api/providers',headers=seller,json={'name':'Salon Smoke Test','category':'Hair and beauty','kind':'Services','city':'Johannesburg','country':'South Africa','remote':True,'bio':'Hair styling and braiding for clients','skills':'hair,brianing,styling','price':10,'capacity':6}))
print('provider',p)
pid=p['id'];l=ok(c.post(f'/api/providers/{pid}/listings',headers=seller,json={'title':'Hair appointment','description':'Wash, style and finish the hair','kind':'Services','price':10,'stock':3}))
lid=l['id'];print('listing',lid)
s=ok(c.get(f'/api/operations/providers/{pid}/schedule'));hours={k:{'open':'09:00','close':'17:00','closed':False} for k in ['mon','tue','wed','thu','fri','sat','sun']}
ok(c.put(f'/api/operations/providers/{pid}/schedule',headers=seller,json={'timezone':'Africa/Johannesburg','hours':hours,'slot_minutes':60,'lead_hours':0}))
assert c.put(f'/api/operations/providers/{pid}/schedule',headers=buyer,json={'timezone':'Africa/Johannesburg','hours':hours}).status_code==403
future=(datetime.date.today()+datetime.timedelta(days=3)).isoformat()
slots=ok(c.get(f'/api/operations/providers/{pid}/slots',params={'day':future}))['slots'];assert slots, 'no slots found'
x=slots[0]
b=ok(c.post('/api/commerce/bookings',headers=buyer,json={'listing_id':lid,'starts_at':x['start'],'ends_at':x['end']}));bid=b['id']
assert c.post('/api/commerce/bookings',headers=buyer,json={'listing_id':lid,'starts_at':x['start'],'ends_at':x['end']}).status_code==409
assert c.get(f'/api/operations/bookings/{bid}/calendar.ics',headers=buyer).status_code==409
ok(c.post(f'/api/commerce/bookings/{bid}/status',headers=seller,json={'status':'confirmed'}))
r=c.get(f'/api/operations/bookings/{bid}/calendar.ics',headers=buyer);assert r.status_code==200 and 'BEGIN:VEVENT' in r.text
assert c.get(f'/api/operations/bookings/{bid}/calendar.ics').status_code in (401,403)
ok(c.put(f'/api/operations/providers/{pid}/delivery',headers=seller,json={'local_delivery':True,'pickup_available':True,'shipping_regions':['South Africa']}))
assert c.put(f'/api/operations/providers/{pid}/delivery',headers=buyer,json={'local_delivery':False}).status_code==403
assert c.post(f'/api/operations/providers/{pid}/verification/request',headers=seller).status_code==422 # requires onsite coords
print('SMOKE OK')
