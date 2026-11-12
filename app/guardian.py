"""LAPENG Guardian: evidence-first, human-reviewed trust cases.

Alerts are informational. Automated classification does not establish fraud.
Admin moderation is explicitly opt-in via APP_MODERATOR_USER_IDS. Never grant moderator privileges from an
unverified account email address. This prototype is NOT a KYC vendor.
"""
import os, re, time, json, hashlib, sqlite3
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

LINK = re.compile(r'(?i)(?:https?://|www\.|(?:wa\.me|t\.me)/|(?:paypal\.me|bit\.ly)/)')
DANGER = [
    ('off_platform_payment', re.compile(r'(?i)(?:pay|transfer|send|deposit).{0,55}(?:outside (?:lapeng|the platform)|direct(?:ly)? to (?:my )?(?:bank|wallet)|crypto|gift\s*card|western union)')),
    ('credential_request', re.compile(r'(?i)(?:send|share|tell|give).{0,40}(?:password|otp|one.time code|verification code|cvv|pin number)')),
    ('urgent_pressure', re.compile(r'(?i)(?:pay now or|last chance to pay|act immediately or|send money urgently)')),
]

class SignalIn(BaseModel):
    text: str=Field(min_length=3,max_length=4000)

class CaseIn(BaseModel):
    target_type:str
    target_id:int=Field(ge=1)
    reason:str=Field(min_length=12,max_length=1500)
    evidence:str=Field(default='',max_length=2000)

class ReviewIn(BaseModel):
    status:str
    note:str=Field(min_length=12,max_length=1000)

class AppealIn(BaseModel):
    reason:str=Field(min_length=12,max_length=1500)


def signals(text):
    labels=[key for key,pat in DANGER if pat.search(text)]
    if LINK.search(text) and re.search(r'(?i)(?:pay|checkout|invoice|transfer|deposit)',text):labels.append('external_payment_link')
    return sorted(set(labels))


def register(app,conn,current,throttle):
    router=APIRouter(prefix='/api/guardian',tags=['guardian'])
    with conn() as db:
        db.executescript('''
          CREATE TABLE IF NOT EXISTS guardian_cases(
            id INTEGER PRIMARY KEY, reporter_id INTEGER NOT NULL REFERENCES users(id),
            target_type TEXT NOT NULL,target_id INTEGER NOT NULL,subject_id INTEGER REFERENCES users(id),
            reason TEXT NOT NULL,evidence TEXT NOT NULL DEFAULT '',
            signals_json TEXT NOT NULL DEFAULT '[]',status TEXT NOT NULL DEFAULT 'open',
            decision_note TEXT NOT NULL DEFAULT '',created INTEGER NOT NULL,updated INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS guardian_appeals(
            id INTEGER PRIMARY KEY,case_id INTEGER NOT NULL REFERENCES guardian_cases(id),
            author_id INTEGER NOT NULL REFERENCES users(id),reason TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',decision_note TEXT NOT NULL DEFAULT '',
            created INTEGER NOT NULL,updated INTEGER NOT NULL,
            UNIQUE(case_id,author_id));
          CREATE TABLE IF NOT EXISTS guardian_audit(
            id INTEGER PRIMARY KEY,case_id INTEGER REFERENCES guardian_cases(id),actor_id INTEGER REFERENCES users(id),
            action TEXT NOT NULL,detail TEXT NOT NULL DEFAULT '',created INTEGER NOT NULL);
          CREATE INDEX IF NOT EXISTS guardian_case_reporter ON guardian_cases(reporter_id,created);
          CREATE INDEX IF NOT EXISTS guardian_case_subject ON guardian_cases(subject_id,created);
        ''')

    def is_mod(user):
        configured={int(x.strip()) for x in os.getenv('APP_MODERATOR_USER_IDS','').split(',') if x.strip().isdigit()}
        return bool(configured and user['id'] in configured)

    def target_owner(db,kind,key):
        if kind=='provider':
            x=db.execute('SELECT owner_id FROM providers WHERE id=?',(key,)).fetchone()
        elif kind=='listing':
            x=db.execute('SELECT p.owner_id FROM listings l JOIN providers p ON p.id=l.provider_id WHERE l.id=?',(key,)).fetchone()
        elif kind=='request':
            x=db.execute('SELECT buyer_id FROM requests WHERE id=?',(key,)).fetchone()
        elif kind=='message':
            x=db.execute('SELECT sender_id FROM messages WHERE id=?',(key,)).fetchone()
        elif kind=='user':
            x=db.execute('SELECT id FROM users WHERE id=?',(key,)).fetchone()
        elif kind=='order':
            x=db.execute('SELECT buyer_id FROM shop_orders WHERE id=?',(key,)).fetchone()
        else:raise HTTPException(422,'Unsupported report target')
        if not x:raise HTTPException(404,'Target not found')
        return x[0]

    def permitted(db,case,user):
        return is_mod(user) or case['reporter_id']==user['id'] or case['subject_id']==user['id']

    @router.get('/me')
    def guardian_me(u=Depends(current)):
        return {'moderator':is_mod(u),'policy':'Human review; no automatic account suspension or identity verification'}

    @router.post('/check')
    def check(item:SignalIn,request:Request):
        throttle('guardian-check:'+str(request.client.host if request.client else 'unknown'),35,3600)
        found=signals(item.text)
        return {'signals':found,'needs_caution':bool(found),
                'guidance':'Potential warning signs found. Do not share passwords or one-time codes. Keep payments within the supported checkout and report suspicious behaviour.' if found else 'No common warning patterns detected. This does not guarantee that an offer or user is safe.',
                'note':'Heuristic screening only; not an allegation or identity verification. Message text is not stored by this check.'}

    @router.post('/cases')
    def create_case(x:CaseIn,u=Depends(current)):
        throttle('guardian-report:'+str(u['id']),12,3600)
        with conn() as db:
            subject=target_owner(db,x.target_type,x.target_id)
            # Reports of private messages/orders only accepted from existing participants.
            if x.target_type=='message':
                msg=db.execute('SELECT request_id,sender_id FROM messages WHERE id=?',(x.target_id,)).fetchone()
                req=db.execute('SELECT buyer_id FROM requests WHERE id=?',(msg['request_id'],)).fetchone()
                seller=db.execute("SELECT 1 FROM proposals q JOIN providers p ON p.id=q.provider_id WHERE q.request_id=? AND q.status='accepted' AND p.owner_id=?",(msg['request_id'],u['id'])).fetchone()
                if u['id']!=req['buyer_id'] and u['id']!=msg['sender_id'] and not seller:raise HTTPException(403,'Only message participants can report this message')
            if x.target_type=='order':
                row=db.execute('SELECT o.buyer_id,p.owner_id FROM shop_orders o JOIN providers p ON p.id=o.provider_id WHERE o.id=?',(x.target_id,)).fetchone()
                if u['id'] not in (row['buyer_id'],row['owner_id']):raise HTTPException(403,'Only an order participant can report an order')
                # The reported party must be the *other* participant, so they
                # have case visibility and a meaningful right to appeal.
                subject=row['owner_id'] if u['id']==row['buyer_id'] else row['buyer_id']
            if db.execute('SELECT 1 FROM guardian_cases WHERE reporter_id=? AND target_type=? AND target_id=? AND status IN (\'open\',\'under_review\')',(u['id'],x.target_type,x.target_id)).fetchone():raise HTTPException(409,'You already have an open case for this item')
            now=int(time.time());flags=signals(x.reason+' '+x.evidence)
            cid=db.execute('INSERT INTO guardian_cases(reporter_id,target_type,target_id,subject_id,reason,evidence,signals_json,created,updated) VALUES(?,?,?,?,?,?,?,?,?)',
                (u['id'],x.target_type,x.target_id,subject,x.reason,x.evidence,json.dumps(flags),now,now)).lastrowid
            db.execute('INSERT INTO guardian_audit(case_id,actor_id,action,detail,created) VALUES(?,?,?,?,?)',(cid,u['id'],'submitted','User report received',now))
            return {'id':cid,'status':'open','signals':flags,'note':'A report is not evidence of wrongdoing. A reviewer must assess it.'}

    @router.get('/cases')
    def cases(u=Depends(current)):
        with conn() as db:
            if is_mod(u):
                data=db.execute('SELECT * FROM guardian_cases ORDER BY id DESC LIMIT 100').fetchall()
            else:
                data=db.execute('SELECT * FROM guardian_cases WHERE reporter_id=? OR subject_id=? ORDER BY id DESC LIMIT 100',(u['id'],u['id'])).fetchall()
            result=[]
            for c in data:
                x=dict(c)
                # The report evidence and reporter ID are confidential from the reported party.
                if not is_mod(u) and c['reporter_id']!=u['id']:
                    for key in ('reporter_id','evidence','reason','signals_json'):x.pop(key,None)
                result.append(x)
            return result

    @router.get('/cases/{cid}')
    def case(cid:int,u=Depends(current)):
        with conn() as db:
            c=db.execute('SELECT * FROM guardian_cases WHERE id=?',(cid,)).fetchone()
            if not c:raise HTTPException(404,'Case not found')
            if not permitted(db,c,u):raise HTTPException(403,'Not a case participant')
            result=dict(c)
            if not is_mod(u) and c['reporter_id']!=u['id']:
                for key in ('reporter_id','evidence','reason','signals_json'):result.pop(key,None)
            result['appeals']=[dict(a) for a in db.execute('SELECT id,author_id,status,decision_note,created FROM guardian_appeals WHERE case_id=?',(cid,)) if is_mod(u) or a['author_id']==u['id']]
            return result

    @router.post('/cases/{cid}/decision')
    def decide(cid:int,x:ReviewIn,u=Depends(current)):
        if not is_mod(u):raise HTTPException(403,'Moderator permission required')
        if x.status not in ('under_review','resolved','dismissed'):raise HTTPException(422,'Invalid decision')
        with conn() as db:
            c=db.execute('SELECT status FROM guardian_cases WHERE id=?',(cid,)).fetchone()
            if not c:raise HTTPException(404,'Case not found')
            if c['status'] not in ('open','under_review'):raise HTTPException(409,'Case is already closed')
            now=int(time.time())
            db.execute('UPDATE guardian_cases SET status=?,decision_note=?,updated=? WHERE id=?',(x.status,x.note,now,cid))
            db.execute('INSERT INTO guardian_audit(case_id,actor_id,action,detail,created) VALUES(?,?,?,?,?)',(cid,u['id'],x.status,x.note,now))
            return {'status':x.status,'note':'A moderation decision is not automatic proof of fraud'}

    @router.post('/cases/{cid}/appeals')
    def appeal(cid:int,x:AppealIn,u=Depends(current)):
        with conn() as db:
            c=db.execute('SELECT * FROM guardian_cases WHERE id=?',(cid,)).fetchone()
            if not c:raise HTTPException(404,'Case not found')
            if c['subject_id']!=u['id']:raise HTTPException(403,'Only the reported account can appeal')
            if c['status'] not in ('resolved','dismissed'):raise HTTPException(409,'Wait for a completed decision')
            now=int(time.time())
            try:aid=db.execute('INSERT INTO guardian_appeals(case_id,author_id,reason,created,updated) VALUES(?,?,?,?,?)',(cid,u['id'],x.reason,now,now)).lastrowid
            except sqlite3.IntegrityError:raise HTTPException(409,'You have already appealed this case')
            db.execute('INSERT INTO guardian_audit(case_id,actor_id,action,detail,created) VALUES(?,?,?,?,?)',(cid,u['id'],'appealed','Appeal submitted',now))
            return {'id':aid,'status':'pending'}

    @router.get('/appeals')
    def moderator_appeals(u=Depends(current)):
        if not is_mod(u):raise HTTPException(403,'Moderator permission required')
        with conn() as db:
            return [dict(x) for x in db.execute("SELECT a.id,a.case_id,a.author_id,a.reason,a.status,a.created FROM guardian_appeals a WHERE a.status='pending' ORDER BY id DESC LIMIT 100")]

    @router.post('/appeals/{aid}/decision')
    def appeal_decision(aid:int,x:ReviewIn,u=Depends(current)):
        if not is_mod(u):raise HTTPException(403,'Moderator permission required')
        if x.status not in ('upheld','reversed'):raise HTTPException(422,'Invalid appeal outcome')
        with conn() as db:
            a=db.execute('SELECT * FROM guardian_appeals WHERE id=?',(aid,)).fetchone()
            if not a:raise HTTPException(404,'Appeal not found')
            if a['status']!='pending':raise HTTPException(409,'Appeal already decided')
            now=int(time.time())
            db.execute('UPDATE guardian_appeals SET status=?,decision_note=?,updated=? WHERE id=?',(x.status,x.note,now,aid))
            if x.status=='reversed':db.execute("UPDATE guardian_cases SET status='dismissed',decision_note=?,updated=? WHERE id=?",(x.note,now,a['case_id']))
            db.execute('INSERT INTO guardian_audit(case_id,actor_id,action,detail,created) VALUES(?,?,?,?,?)',(a['case_id'],u['id'],'appeal_'+x.status,x.note,now))
            return {'status':x.status}

    @router.get('/cases/{cid}/audit')
    def audit(cid:int,u=Depends(current)):
        if not is_mod(u):raise HTTPException(403,'Moderator permission required')
        with conn() as db:
            if not db.execute('SELECT 1 FROM guardian_cases WHERE id=?',(cid,)).fetchone():raise HTTPException(404,'Case not found')
            return [dict(r) for r in db.execute('SELECT actor_id,action,detail,created FROM guardian_audit WHERE case_id=? ORDER BY id',(cid,))]

    app.include_router(router)
