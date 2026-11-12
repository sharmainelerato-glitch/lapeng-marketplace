"""Guardian permissions, audit, appeals, and uploaded image safety. No outside services."""
import io, base64
from PIL import Image
from test_app import client,auth


def create_provider(headers,name):
    p=client.post('/api/providers',headers=headers,json={
        'name':name,'category':'Clothing','kind':'Products','city':'Pretoria','country':'South Africa',
        'bio':'Independent clothing and accessories for local customers.',
        'skills':'sewing,design','price':100,'capacity':3})
    assert p.status_code==200,p.text
    return p.json()['id']


def test_guardian_flags_are_cautious_and_not_stored():
    suspicious=client.post('/api/guardian/check',json={'text':'Send me your OTP verification code and pay outside LAPENG.'})
    assert suspicious.status_code==200
    assert 'credential_request' in suspicious.json()['signals']
    assert suspicious.json()['needs_caution']
    benign=client.post('/api/guardian/check',json={'text':'I can tailor a shirt in blue.'}).json()
    assert not benign['needs_caution']
    assert 'does not guarantee' in benign['guidance']


def test_case_permissions_appeal_and_audit(monkeypatch):
    reporter=auth('Case Reporter','casereporter@lapeng.test')
    subject=auth('Case Seller','caseseller@lapeng.test')
    outsider=auth('Case Stranger','casestranger@lapeng.test')
    moderator=auth('Case Moderator','moderator@lapeng.test')
    pid=create_provider(subject,'Case Test Seller')
    payload={'target_type':'provider','target_id':pid,'reason':'Portfolio descriptions appear misleading and copied from another source.', 'evidence':'Example evidence shared with the reviewing team only.'}
    created=client.post('/api/guardian/cases',headers=reporter,json=payload)
    assert created.status_code==200,created.text
    cid=created.json()['id']
    assert client.post('/api/guardian/cases',headers=reporter,json=payload).status_code==409
    assert client.get(f'/api/guardian/cases/{cid}',headers=outsider).status_code==403
    visible=client.get('/api/guardian/cases',headers=subject).json()[0]
    assert 'evidence' not in visible and 'reason' not in visible and 'reporter_id' not in visible
    assert client.post(f'/api/guardian/cases/{cid}/decision',headers=subject,json={'status':'resolved','note':'A human reviewed this report carefully.'}).status_code==403
    from app.main import conn
    with conn() as db:
        admin_id=db.execute("SELECT id FROM users WHERE email='moderator@lapeng.test'").fetchone()['id']
    monkeypatch.setenv('APP_MODERATOR_USER_IDS',str(admin_id))
    assert client.get('/api/guardian/me',headers=moderator).json()['moderator']
    assert client.post(f'/api/guardian/cases/{cid}/decision',headers=moderator,json={'status':'resolved','note':'Evidence suggests improvement is appropriate.'}).status_code==200
    assert client.post(f'/api/guardian/cases/{cid}/appeals',headers=reporter,json={'reason':'I disagree with the review decision for this case.'}).status_code==403
    appeal=client.post(f'/api/guardian/cases/{cid}/appeals',headers=subject,json={'reason':'My portfolio is original and I can provide supporting files.'})
    assert appeal.status_code==200,appeal.text
    aid=appeal.json()['id']
    assert client.post(f'/api/guardian/appeals/{aid}/decision',headers=moderator,json={'status':'reversed','note':'New documents were evaluated and decision reversed.'}).status_code==200
    assert client.get(f'/api/guardian/cases/{cid}',headers=reporter).json()['status']=='dismissed'
    audit=client.get(f'/api/guardian/cases/{cid}/audit',headers=moderator).json()
    assert [i['action'] for i in audit]==['submitted','resolved','appealed','appeal_reversed']
    assert client.get(f'/api/guardian/cases/{cid}/audit',headers=reporter).status_code==403


def test_images_reencoded_and_work_for_providers():
    seller=auth('Photo Seller','photoseller@lapeng.test')
    other=auth('Other Seller','otherphotos@lapeng.test')
    pid=create_provider(seller,'Real Pictures Studio')
    img=Image.new('RGBA',(40,40),(150,10,20,127))
    f=io.BytesIO();img.save(f,format='PNG')
    blob=base64.b64encode(f.getvalue()).decode()
    response=client.post(f'/api/providers/{pid}/photos',headers=seller,json={'data':blob,'role':'before','caption':'A finished example'})
    assert response.status_code==200,response.text
    output=client.get(response.json()['url'])
    assert output.status_code==200
    assert output.content.startswith(b'\xff\xd8\xff')
    assert client.post(f'/api/providers/{pid}/photos',headers=other,json={'data':blob,'role':'work','caption':'Not my portfolio'}).status_code==403
    assert client.post(f'/api/providers/{pid}/photos',headers=seller,json={'data':base64.b64encode(b'<script>oops</script>').decode(),'role':'work'}).status_code in (413,415)
