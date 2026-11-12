"""Private buyer-to-provider conversations: no public opportunity posts or automatic payments."""
import time
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

class StartConversation(BaseModel):
    provider_id:int=Field(gt=0)
    listing_id:int|None=Field(default=None,gt=0)
    message:str=Field(min_length=2,max_length=1500)

class NewMessage(BaseModel):
    body:str=Field(min_length=1,max_length=1500)

def register(app, conn, current, throttle):
    router=APIRouter(prefix='/api/conversations',tags=['Private provider messages'])
    with conn() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS private_threads (
            id INTEGER PRIMARY KEY,
            buyer_id INTEGER NOT NULL REFERENCES users(id),
            provider_id INTEGER NOT NULL REFERENCES providers(id),
            listing_id INTEGER REFERENCES listings(id),
            created INTEGER NOT NULL,
            updated INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS private_thread_messages (
            id INTEGER PRIMARY KEY,
            thread_id INTEGER NOT NULL REFERENCES private_threads(id),
            sender_id INTEGER NOT NULL REFERENCES users(id),
            body TEXT NOT NULL,
            created INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS private_threads_buyer ON private_threads(buyer_id,updated);
        CREATE INDEX IF NOT EXISTS private_threads_provider ON private_threads(provider_id,updated);
        CREATE INDEX IF NOT EXISTS private_messages_thread ON private_thread_messages(thread_id,id);
        ''')
    def check(db,tid,u):
        t=db.execute('''SELECT t.*,p.owner_id seller_id,p.name provider_name,
            l.title listing_title, ub.name buyer_name
            FROM private_threads t JOIN providers p ON t.provider_id=p.id
            JOIN users ub ON t.buyer_id=ub.id
            LEFT JOIN listings l ON l.id=t.listing_id WHERE t.id=?''',(tid,)).fetchone()
        if not t or u['id'] not in (t['buyer_id'],t['seller_id']):raise HTTPException(404,'Conversation not found')
        return dict(t)
    @router.post('')
    def start(payload:StartConversation,u=Depends(current)):
        throttle('direct-message:'+str(u['id']),40,3600)
        with conn() as db:
            p=db.execute('SELECT id,owner_id FROM providers WHERE id=?',(payload.provider_id,)).fetchone()
            if not p or p['owner_id'] is None:raise HTTPException(404,'Provider not available for messaging')
            if p['owner_id']==u['id']:raise HTTPException(403,'You cannot message your own business')
            if payload.listing_id is not None and not db.execute('SELECT 1 FROM listings WHERE id=? AND provider_id=?',(payload.listing_id,p['id'])).fetchone():raise HTTPException(422,'Listing does not belong to this business')
            now=int(time.time())
            # Reuse an existing buyer-business-listing thread, but not another buyer's.
            t=db.execute('SELECT id FROM private_threads WHERE buyer_id=? AND provider_id=? AND listing_id IS ? ORDER BY id DESC LIMIT 1',(u['id'],p['id'],payload.listing_id)).fetchone()
            if t:tid=t['id'];db.execute('UPDATE private_threads SET updated=? WHERE id=?',(now,tid))
            else:tid=db.execute('INSERT INTO private_threads(buyer_id,provider_id,listing_id,created,updated) VALUES(?,?,?,?,?)',(u['id'],p['id'],payload.listing_id,now,now)).lastrowid
            db.execute('INSERT INTO private_thread_messages(thread_id,sender_id,body,created) VALUES(?,?,?,?)',(tid,u['id'],payload.message.strip(),now))
            return {'id':tid,'notice':'Private enquiry delivered inside LAPENG. No booking or payment has occurred.'}
    @router.get('')
    def list_threads(u=Depends(current)):
        with conn() as db:
            return [dict(r) for r in db.execute('''SELECT t.id,t.buyer_id,t.provider_id,t.listing_id,t.updated,
                p.name provider_name,l.title listing_title,ub.name buyer_name,
                (SELECT m.body FROM private_thread_messages m WHERE m.thread_id=t.id ORDER BY m.id DESC LIMIT 1) last_message
                FROM private_threads t JOIN providers p ON p.id=t.provider_id
                JOIN users ub ON ub.id=t.buyer_id LEFT JOIN listings l ON l.id=t.listing_id
                WHERE t.buyer_id=? OR p.owner_id=? ORDER BY t.updated DESC LIMIT 100''',(u['id'],u['id']))]
    @router.get('/{tid}')
    def details(tid:int,u=Depends(current)):
        with conn() as db:
            t=check(db,tid,u)
            messages=[dict(r) for r in db.execute('''SELECT m.id,m.sender_id,m.body,m.created,users.name sender_name
                FROM private_thread_messages m JOIN users ON users.id=m.sender_id
                WHERE m.thread_id=? ORDER BY m.id LIMIT 300''',(tid,))]
            return {'thread':t,'messages':messages,'notice':'LAPENG private enquiries do not authorize payments or confirm bookings.'}
    @router.post('/{tid}/messages')
    def reply(tid:int,payload:NewMessage,u=Depends(current)):
        throttle('direct-message:'+str(u['id']),40,3600)
        with conn() as db:
            check(db,tid,u)
            now=int(time.time())
            db.execute('INSERT INTO private_thread_messages(thread_id,sender_id,body,created) VALUES(?,?,?,?)',(tid,u['id'],payload.body.strip(),now))
            db.execute('UPDATE private_threads SET updated=? WHERE id=?',(now,tid))
            try:
                from app.guardian import signals
                flags=signals(payload.body)
            except ImportError:flags=[]
            return {'ok':True,'warning':'Potential payment diversion or scam wording detected; verify before proceeding.' if flags else None}
    app.include_router(router)
