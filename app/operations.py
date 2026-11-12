"""Local services operations. Human-confirmed bookings, no fabricated location verification.
No third-party calendar provider, routing API, email sender, or PayPal payout integration is implied.
"""
from __future__ import annotations
import json, time, secrets, hashlib, hmac, os, datetime, zoneinfo, httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

DAYS=('mon','tue','wed','thu','fri','sat','sun')

def default_hours():
    return {day: {'open':'09:00','close':'17:00','closed':day in ('sat','sun')} for day in DAYS}

class ScheduleIn(BaseModel):
    timezone:str=Field(default='Africa/Johannesburg',max_length=70)
    hours:dict=Field(default_factory=default_hours)
    slot_minutes:int=Field(default=60,ge=15,le=480)
    lead_hours:int=Field(default=2,ge=0,le=720)
    break_minutes:int=Field(default=0,ge=0,le=120)

class DeliveryIn(BaseModel):
    local_delivery:bool=False
    delivery_radius_km:int=Field(default=20,ge=1,le=1000)
    pickup_available:bool=True
    shipping_regions:list[str]=Field(default_factory=list,max_length=30)
    processing_days:int=Field(default=2,ge=0,le=60)
    notes:str=Field(default='',max_length=500)

class VerificationIn(BaseModel):
    outcome:str
    note:str=Field(min_length=12,max_length=700)

class LocationPreferenceIn(BaseModel):
    city:str=Field(default='',max_length=90)
    country:str=Field(default='',max_length=90)
    use_nearby:bool=False
    # Avoid storing precise device coordinates, especially on long-lived accounts.

def validate_schedule(x:ScheduleIn):
    try: zoneinfo.ZoneInfo(x.timezone)
    except Exception: raise HTTPException(422,'Use a supported IANA time zone, such as Africa/Johannesburg')
    if set(x.hours)!=set(DAYS): raise HTTPException(422,'Provide exactly Monday to Sunday hours')
    for day,entry in x.hours.items():
        if not isinstance(entry,dict):raise HTTPException(422,'Invalid opening hours')
        for field in ('open','close'):
            v=entry.get(field)
            if not isinstance(v,str) or len(v)!=5 or v[2]!=':' or not v[:2].isdigit() or not v[3:].isdigit() or not (0<=int(v[:2])<24 and 0<=int(v[3:])<60):raise HTTPException(422,'Use HH:MM opening hours')
        if entry['open']>=entry['close'] and not entry.get('closed'):raise HTTPException(422,'Closing time must follow opening time')

def register(app,conn,current):
    router=APIRouter(prefix='/api/operations',tags=['operations'])
    def fetch(db,q,params=()):return db.execute(q,params).fetchone()
    def owned(db,pid,uid):
        p=fetch(db,'SELECT * FROM providers WHERE id=?',(pid,))
        if not p:raise HTTPException(404,'Provider not found')
        if p['owner_id'] != uid:raise HTTPException(403,'Only this provider owner can change settings')
        return p
    def read_schedule(db,pid):
        row=fetch(db,'SELECT * FROM provider_schedule WHERE provider_id=?',(pid,))
        if not row:return {'timezone':'Africa/Johannesburg','hours':default_hours(),'slot_minutes':60,'lead_hours':2,'break_minutes':0,'configured':False}
        return {'timezone':row['timezone'],'hours':json.loads(row['hours_json']),'slot_minutes':row['slot_minutes'],'lead_hours':row['lead_hours'],'break_minutes':row['break_minutes'],'configured':True}
    with conn() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS provider_schedule(provider_id INTEGER PRIMARY KEY REFERENCES providers(id),timezone TEXT NOT NULL,hours_json TEXT NOT NULL,slot_minutes INTEGER NOT NULL,lead_hours INTEGER NOT NULL,break_minutes INTEGER NOT NULL DEFAULT 0,updated INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS provider_delivery(provider_id INTEGER PRIMARY KEY REFERENCES providers(id),local_delivery INTEGER NOT NULL DEFAULT 0,delivery_radius_km INTEGER NOT NULL DEFAULT 20,pickup_available INTEGER NOT NULL DEFAULT 1,shipping_regions_json TEXT NOT NULL DEFAULT '[]',processing_days INTEGER NOT NULL DEFAULT 2,notes TEXT NOT NULL DEFAULT '',updated INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS provider_verification(provider_id INTEGER PRIMARY KEY REFERENCES providers(id),status TEXT NOT NULL DEFAULT 'unverified',reviewed_by INTEGER REFERENCES users(id),note TEXT NOT NULL DEFAULT '',updated INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS account_location_prefs(user_id INTEGER PRIMARY KEY REFERENCES users(id),city TEXT NOT NULL DEFAULT '',country TEXT NOT NULL DEFAULT '',use_nearby INTEGER NOT NULL DEFAULT 0,updated INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS booking_reminder_log(booking_id INTEGER NOT NULL REFERENCES service_bookings(id),reminder_kind TEXT NOT NULL,created INTEGER NOT NULL,PRIMARY KEY(booking_id,reminder_kind));
        CREATE TABLE IF NOT EXISTS notification_preferences(user_id INTEGER PRIMARY KEY REFERENCES users(id),email_appointment_reminders INTEGER NOT NULL DEFAULT 0,updated INTEGER NOT NULL);
        """)
    @router.get('/listings/{lid}/provider')
    def listing_provider(lid:int):
        with conn() as db:
            row=fetch(db,'SELECT provider_id FROM listings WHERE id=?',(lid,))
            if not row:raise HTTPException(404,'Listing not found')
            return {'provider_id':row['provider_id']}
    @router.get('/providers/{pid}/schedule')
    def schedule_get(pid:int):
        with conn() as db:
            if not fetch(db,'SELECT 1 FROM providers WHERE id=?',(pid,)):raise HTTPException(404,'Provider not found')
            return read_schedule(db,pid)
    @router.put('/providers/{pid}/schedule')
    def schedule_save(pid:int,x:ScheduleIn,u=Depends(current)):
        validate_schedule(x)
        with conn() as db:
            owned(db,pid,u['id'])
            db.execute('INSERT INTO provider_schedule(provider_id,timezone,hours_json,slot_minutes,lead_hours,break_minutes,updated) VALUES(?,?,?,?,?,?,?) ON CONFLICT(provider_id) DO UPDATE SET timezone=excluded.timezone,hours_json=excluded.hours_json,slot_minutes=excluded.slot_minutes,lead_hours=excluded.lead_hours,break_minutes=excluded.break_minutes,updated=excluded.updated',(pid,x.timezone,json.dumps(x.hours),x.slot_minutes,x.lead_hours,x.break_minutes,int(time.time())))
            return {'saved':True}
    @router.get('/providers/{pid}/slots')
    def available_slots(pid:int,day:str):
        try: target=datetime.date.fromisoformat(day)
        except ValueError: raise HTTPException(422,'Use YYYY-MM-DD date')
        if not datetime.date.today()<=target<=datetime.date.today()+datetime.timedelta(days=120):raise HTTPException(422,'Choose a date in the next 120 days')
        with conn() as db:
            if not fetch(db,'SELECT 1 FROM providers WHERE id=?',(pid,)):raise HTTPException(404,'Provider not found')
            s=read_schedule(db,pid)
            if not s['configured']:return {'slots':[],'timezone':s['timezone'],'note':'Provider has not published opening hours'}
            h=s['hours'][DAYS[target.weekday()]]
            if h.get('closed'):return {'slots':[],'timezone':s['timezone']}
            tz=zoneinfo.ZoneInfo(s['timezone'])
            lo=datetime.datetime.fromisoformat(f'{day}T{h["open"]}').replace(tzinfo=tz)
            hi=datetime.datetime.fromisoformat(f'{day}T{h["close"]}').replace(tzinfo=tz)
            busy=[(r['starts_at'],r['ends_at']) for r in db.execute("SELECT starts_at,ends_at FROM service_bookings WHERE provider_id=? AND status IN ('confirmed','requested') AND starts_at<? AND ends_at>?",(pid,int(hi.timestamp()),int(lo.timestamp())))]
            slots=[]; start=lo; now=int(time.time())
            while start+datetime.timedelta(minutes=s['slot_minutes'])<=hi and len(slots)<60:
                end=start+datetime.timedelta(minutes=s['slot_minutes']); a=int(start.timestamp());b=int(end.timestamp())
                if a>=now+s['lead_hours']*3600 and not any(a<y+s['break_minutes']*60 and b>x-s['break_minutes']*60 for x,y in busy):
                    slots.append({'start':a,'end':b,'label':start.strftime('%H:%M')})
                start=end
            return {'slots':slots,'timezone':s['timezone'],'duration_minutes':s['slot_minutes']}
    @router.get('/providers/{pid}/delivery')
    def delivery_get(pid:int):
        with conn() as db:
            if not fetch(db,'SELECT 1 FROM providers WHERE id=?',(pid,)):raise HTTPException(404,'Provider not found')
            row=fetch(db,'SELECT * FROM provider_delivery WHERE provider_id=?',(pid,))
            return {'configured':bool(row),'local_delivery':bool(row['local_delivery']) if row else False,'delivery_radius_km':row['delivery_radius_km'] if row else 20,'pickup_available':bool(row['pickup_available']) if row else True,'shipping_regions':json.loads(row['shipping_regions_json']) if row else [],'processing_days':row['processing_days'] if row else 2,'notes':row['notes'] if row else ''}
    @router.put('/providers/{pid}/delivery')
    def delivery_save(pid:int,x:DeliveryIn,u=Depends(current)):
        if any(len(v)>80 for v in x.shipping_regions):raise HTTPException(422,'Shipping region name too long')
        with conn() as db:
            owned(db,pid,u['id'])
            db.execute('INSERT INTO provider_delivery(provider_id,local_delivery,delivery_radius_km,pickup_available,shipping_regions_json,processing_days,notes,updated) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(provider_id) DO UPDATE SET local_delivery=excluded.local_delivery,delivery_radius_km=excluded.delivery_radius_km,pickup_available=excluded.pickup_available,shipping_regions_json=excluded.shipping_regions_json,processing_days=excluded.processing_days,notes=excluded.notes,updated=excluded.updated',(pid,int(x.local_delivery),x.delivery_radius_km,int(x.pickup_available),json.dumps(x.shipping_regions),x.processing_days,x.notes,int(time.time())))
            return {'saved':True,'note':'These are provider-published service regions; carrier rates and actual delivery eligibility are not verified.'}
    @router.post('/providers/{pid}/verification/request')
    def verification_request(pid:int,u=Depends(current)):
        with conn() as db:
            p=owned(db,pid,u['id'])
            if p['latitude'] is None or p['longitude'] is None:raise HTTPException(422,'Configure a service location first')
            db.execute("INSERT INTO provider_verification(provider_id,status,updated) VALUES(?,'pending_review',?) ON CONFLICT(provider_id) DO UPDATE SET status='pending_review',reviewed_by=NULL,note='',updated=excluded.updated",(pid,int(time.time())))
            return {'status':'pending_review','note':'Submission recorded. No physical location has been verified. A moderator needs independent evidence and authority to review.'}
    @router.post('/providers/{pid}/verification/decision')
    def verification_decision(pid:int,x:VerificationIn,u=Depends(current)):
        admins={int(v.strip()) for v in os.getenv('APP_MODERATOR_USER_IDS','').split(',') if v.strip().isdigit()}
        if u['id'] not in admins:raise HTTPException(403,'Only a configured moderator may review location claims')
        if x.outcome not in ('verified','rejected'):raise HTTPException(422,'Invalid decision')
        with conn() as db:
            row=fetch(db,'SELECT status FROM provider_verification WHERE provider_id=?',(pid,))
            if not row or row['status']!='pending_review':raise HTTPException(409,'No pending location review')
            db.execute('UPDATE provider_verification SET status=?,reviewed_by=?,note=?,updated=? WHERE provider_id=?',(x.outcome,u['id'],x.note,int(time.time()),pid))
            return {'status':x.outcome,'note':'Manual assessment only. LAPENG has not independently validated land registry or government documentation.'}
    @router.get('/verification/queue')
    def verification_queue(u=Depends(current)):
        admins={int(v.strip()) for v in os.getenv('APP_MODERATOR_USER_IDS','').split(',') if v.strip().isdigit()}
        if u['id'] not in admins:raise HTTPException(403,'Moderator access required')
        with conn() as db:
            return [dict(r) for r in db.execute("SELECT p.id,p.name,p.city,p.country,p.latitude,p.longitude,v.status FROM provider_verification v JOIN providers p ON p.id=v.provider_id WHERE v.status='pending_review' ORDER BY v.updated LIMIT 50")]
    @router.get('/providers/{pid}/verification')
    def verification_get(pid:int):
        with conn() as db:
            if not fetch(db,'SELECT 1 FROM providers WHERE id=?',(pid,)):raise HTTPException(404,'Provider not found')
            row=fetch(db,'SELECT status,updated FROM provider_verification WHERE provider_id=?',(pid,))
            return dict(row) if row else {'status':'unverified'}
    @router.get('/account/location')
    def location_get(u=Depends(current)):
        with conn() as db:
            row=fetch(db,'SELECT city,country,use_nearby FROM account_location_prefs WHERE user_id=?',(u['id'],))
            return dict(row) if row else {'city':'','country':'','use_nearby':0}
    @router.put('/account/location')
    def location_save(x:LocationPreferenceIn,u=Depends(current)):
        with conn() as db:
            db.execute('INSERT INTO account_location_prefs(user_id,city,country,use_nearby,updated) VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET city=excluded.city,country=excluded.country,use_nearby=excluded.use_nearby,updated=excluded.updated',(u['id'],x.city.strip(),x.country.strip(),int(x.use_nearby),int(time.time())))
            return {'saved':True,'note':'Only your chosen city/country preference is stored, not GPS coordinates.'}
    @router.get('/bookings/{bid}/calendar.ics')
    def calendar_event(bid:int,u=Depends(current)):
        with conn() as db:
            b=fetch(db,'SELECT b.*,l.title,p.name provider_name,p.owner_id FROM service_bookings b JOIN listings l ON l.id=b.listing_id JOIN providers p ON p.id=b.provider_id WHERE b.id=?',(bid,))
            if not b:raise HTTPException(404,'Booking not found')
            if u['id'] not in (b['buyer_id'],b['owner_id']):raise HTTPException(403,'Only booking participants can export this appointment')
            if b['status']!='confirmed':raise HTTPException(409,'Appointment must be confirmed')
            esc=lambda s:str(s).replace('\\','\\\\').replace('\n','\\n').replace(',','\\,').replace(';','\\;')[:250]
            stamp=lambda ts:datetime.datetime.fromtimestamp(ts,datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
            raw='\r\n'.join(['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//LAPENG//Appointments//EN','BEGIN:VEVENT',f'UID:lapeng-booking-{bid}@lapeng.local',f'DTSTAMP:{stamp(int(time.time()))}',f'DTSTART:{stamp(b["starts_at"])}',f'DTEND:{stamp(b["ends_at"])}',f'SUMMARY:{esc(b["title"])}',f'DESCRIPTION:{esc("Appointment with "+b["provider_name"])}','END:VEVENT','END:VCALENDAR',''])
            return Response(raw,media_type='text/calendar',headers={'Content-Disposition':f'attachment; filename="lapeng-booking-{bid}.ics"','Cache-Control':'private, no-store'})
    @router.get('/notifications/preferences')
    def notification_preferences(u=Depends(current)):
        with conn() as db:
            row=fetch(db,'SELECT email_appointment_reminders FROM notification_preferences WHERE user_id=?',(u['id'],))
            return {'email_appointment_reminders':bool(row['email_appointment_reminders']) if row else False,'smtp_configured':bool(os.getenv('LAPENG_SMTP_HOST')),'note':'Emails are opt-in and require a separately scheduled reminder worker.'}
    @router.put('/notifications/preferences')
    def update_notification_preferences(x:dict,u=Depends(current)):
        if set(x)!={'email_appointment_reminders'} or type(x['email_appointment_reminders']) is not bool:raise HTTPException(422,'Specify an email reminder preference')
        with conn() as db:
            db.execute('INSERT INTO notification_preferences(user_id,email_appointment_reminders,updated) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET email_appointment_reminders=excluded.email_appointment_reminders,updated=excluded.updated',(u['id'],int(x['email_appointment_reminders']),int(time.time())))
            return {'saved':True}
    @router.get('/reminders')
    def reminders(u=Depends(current)):
        # In-app reminders on visit, not email/push and not background scheduling.
        with conn() as db:
            now=int(time.time())
            upcoming=[dict(x) for x in db.execute("SELECT b.id,b.starts_at,l.title,b.status FROM service_bookings b JOIN listings l ON l.id=b.listing_id JOIN providers p ON p.id=b.provider_id WHERE (b.buyer_id=? OR p.owner_id=?) AND b.status='confirmed' AND b.starts_at>? AND b.starts_at<? ORDER BY b.starts_at LIMIT 20",(u['id'],u['id'],now,now+86400))]
            return {'upcoming':upcoming,'note':'These reminders appear when you open LAPENG. Automatic email or push delivery requires a separate worker and notification service.'}
    @router.get('/travel-time')
    async def travel_time(provider_id:int,latitude:float,longitude:float,mode:str='DRIVE',u=Depends(current)):
        if not (-90<=latitude<=90 and -180<=longitude<=180):raise HTTPException(422,'Invalid coordinates')
        if mode not in ('DRIVE','WALK','BICYCLE'):raise HTTPException(422,'Unsupported travel mode')
        key=os.getenv('GOOGLE_ROUTES_API_KEY','').strip()
        if not key:return {'configured':False,'travel_minutes':None,'note':'Google Routes API key not configured. Straight-line location filters remain available.'}
        with conn() as db:
            p=fetch(db,'SELECT latitude,longitude FROM providers WHERE id=?',(provider_id,))
            if not p:raise HTTPException(404,'Provider not found')
            if p['latitude'] is None or p['longitude'] is None:raise HTTPException(409,'Provider location unavailable')
        # No arbitrary URL is accepted, secrets are server-side, and throttle limits costly route queries.
        from app.main import throttle
        throttle('route:'+str(u['id']),25,3600)
        body={'origin':{'location':{'latLng':{'latitude':latitude,'longitude':longitude}}},'destination':{'location':{'latLng':{'latitude':p['latitude'],'longitude':p['longitude']}}},'travelMode':mode}
        try:
            async with httpx.AsyncClient(timeout=9) as client:
                r=await client.post('https://routes.googleapis.com/directions/v2:computeRoutes',json=body,headers={'X-Goog-Api-Key':key,'X-Goog-FieldMask':'routes.duration,routes.distanceMeters'})
                r.raise_for_status(); route=(r.json().get('routes') or [None])[0]
        except (httpx.HTTPError, ValueError):raise HTTPException(503,'Travel-time service unavailable')
        if not route:return {'configured':True,'travel_minutes':None,'note':'No route found'}
        return {'configured':True,'travel_minutes':round(int(route['duration'].removesuffix('s'))/60,1),'road_distance_km':round(route['distanceMeters']/1000,1),'mode':mode,'note':'Routing estimate, not a guarantee of arrival time'}
    @router.get('/routing')
    def route_information(provider_id:int,latitude:float,longitude:float):
        if not (-90<=latitude<=90 and -180<=longitude<=180):raise HTTPException(422,'Invalid coordinates')
        with conn() as db:
            p=fetch(db,'SELECT latitude,longitude,remote,service_radius_km,city,country FROM providers WHERE id=?',(provider_id,))
            if not p:raise HTTPException(404,'Provider not found')
            if p['latitude'] is None or p['longitude'] is None:return {'available':False,'note':'No public service centre is configured'}
            from app.main import distance_km
            km=round(distance_km(latitude,longitude,p['latitude'],p['longitude']),1)
            return {'available':True,'straight_line_km':km,'service_area_eligible':bool(km<=p['service_radius_km']),'travel_minutes':None,'routing_provider_connected':False,'note':'Straight-line distance is not travel time. A routing API is required for real road times.'}
    app.include_router(router)
