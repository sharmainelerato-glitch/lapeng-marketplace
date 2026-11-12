"""Category-aware provider onboarding, public-contact consent, and category-specific details.
All settings are seller-authored; nothing here certifies professional credentials.
"""
import json, re, time
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

class SetupIn(BaseModel):
    business_type: str = Field(default='other', max_length=40)
    booking_enabled: bool = False
    appointment_policy: str = Field(default='', max_length=500)
    service_location_type: str = Field(default='none', max_length=25)
    contact_method: str = Field(default='in_app', max_length=16)
    business_phone: str = Field(default='', max_length=22)
    publish_phone: bool = False
    customer_notes: str = Field(default='', max_length=500)
    details: dict[str,str] = Field(default_factory=dict)

    @field_validator('business_type')
    @classmethod
    def valid_type(cls,v):
        if v not in ('beauty','cosmetics','retail','food','trades','digital','education','events','transport','wellness','other'):
            raise ValueError('Unrecognised business type')
        return v

    @field_validator('contact_method')
    @classmethod
    def valid_contact(cls,v):
        if v not in ('in_app','sms','both'): raise ValueError('Invalid contact method')
        return v

    @field_validator('service_location_type')
    @classmethod
    def valid_location(cls,v):
        if v not in ('none','salon','mobile','both','remote','storefront','delivery'):
            raise ValueError('Invalid service-location type')
        return v

    @field_validator('details')
    @classmethod
    def valid_details(cls,v):
        if len(v)>14 or any(not isinstance(k,str) or not re.fullmatch(r'[a-z_]{2,32}',k) or not isinstance(value,str) or len(value)>280 for k,value in v.items()):
            raise ValueError('Too many or invalid business details')
        return v

DEFAULT={'business_type':'other','booking_enabled':False,'appointment_policy':'',
    'service_location_type':'none','contact_method':'in_app','business_phone':'',
    'publish_phone':False,'customer_notes':'','details':{}}

def register(app,conn,current):
    router=APIRouter(prefix='/api/business-setup',tags=['business-setup'])
    with conn() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS provider_business_setup (
            provider_id INTEGER PRIMARY KEY REFERENCES providers(id) ON DELETE CASCADE,
            setup_json TEXT NOT NULL, updated INTEGER NOT NULL)''')
    def provider(db,pid):
        p=db.execute('SELECT id, owner_id, category, kind FROM providers WHERE id=?',(pid,)).fetchone()
        if not p:raise HTTPException(404,'Business not found')
        return p
    @router.get('/providers/{pid}')
    def get_setup(pid:int,u=Depends(current)):
        with conn() as db:
            p=provider(db,pid)
            row=db.execute('SELECT setup_json FROM provider_business_setup WHERE provider_id=?',(pid,)).fetchone()
            cfg={**DEFAULT,**(json.loads(row['setup_json']) if row else {})}
            if p['owner_id']!=u['id'] and not cfg['publish_phone']:
                cfg['business_phone']=''
            return cfg
    @router.get('/providers/{pid}/public')
    def public_setup(pid:int):
        with conn() as db:
            provider(db,pid)
            row=db.execute('SELECT setup_json FROM provider_business_setup WHERE provider_id=?',(pid,)).fetchone()
            cfg={**DEFAULT,**(json.loads(row['setup_json']) if row else {})}
            return {'booking_enabled':cfg['booking_enabled'],
                    'appointment_policy':cfg['appointment_policy'],
                    'service_location_type':cfg['service_location_type'],
                    'contact_method':cfg['contact_method'] if cfg['publish_phone'] else 'in_app',
                    'business_phone':cfg['business_phone'] if cfg['publish_phone'] else '',
                    'customer_notes':cfg['customer_notes'], 'business_type':cfg['business_type'],
                    'details':cfg['details']}
    @router.put('/providers/{pid}')
    def save_setup(pid:int,setup:SetupIn,u=Depends(current)):
        with conn() as db:
            p=provider(db,pid)
            if p['owner_id']!=u['id']:raise HTTPException(403,'Only the business owner can edit onboarding settings')
            if (setup.publish_phone or setup.contact_method in ('sms','both')) and not re.fullmatch(r'\+[1-9]\d{7,14}',setup.business_phone):
                raise HTTPException(422,'Use a valid international-format business number (e.g. +27111234567) before enabling text contact')
            if not setup.publish_phone:setup.contact_method='in_app'
            if setup.booking_enabled and setup.service_location_type in ('none','storefront','delivery'):
                raise HTTPException(422,'Choose a supported appointment location type')
            data=setup.model_dump()
            db.execute('''INSERT INTO provider_business_setup(provider_id,setup_json,updated)
                VALUES(?,?,?) ON CONFLICT(provider_id) DO UPDATE SET
                setup_json=excluded.setup_json,updated=excluded.updated''',(pid,json.dumps(data),int(time.time())))
            return {'saved':True,'note':'Provider supplied information; credentials, address and phone ownership are not verified.'}
    app.include_router(router)
