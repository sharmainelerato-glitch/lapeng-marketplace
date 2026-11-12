import os, sys, time, importlib
from fastapi.testclient import TestClient

def test_schedule_validation():
 from app.operations import ScheduleIn, validate_schedule, default_hours
 s=ScheduleIn(hours=default_hours(),timezone='Africa/Johannesburg')
 validate_schedule(s)
 assert len(s.hours)==7

def test_endpoints_exist():
 from app.main import app
 urls={getattr(r,'path','') for r in app.routes}
 for item in ['/api/operations/providers/{pid}/schedule','/api/operations/providers/{pid}/slots','/api/operations/providers/{pid}/delivery','/api/operations/reminders','/api/operations/bookings/{bid}/calendar.ics','/api/operations/travel-time']:
  assert item in urls

def test_public_schedule_and_verification():
 from app.main import app
 client=TestClient(app)
 data=client.get('/api/providers').json()
 assert data
 pid=data[0]['id']
 assert client.get(f'/api/operations/providers/{pid}/schedule').status_code==200
 assert client.get(f'/api/operations/providers/{pid}/verification').json()['status'] in ('unverified','pending_review','verified','rejected')
 assert client.post(f'/api/operations/providers/{pid}/verification/request').status_code in (401,403)

def test_route_without_auth_restricted():
 from app.main import app
 client=TestClient(app)
 assert client.get('/api/operations/travel-time',params={'provider_id':1,'latitude':-26.2,'longitude':28.0}).status_code in (401,403)
