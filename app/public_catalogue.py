# Opt-in, idempotent importer for public demonstration catalogue only.
import json
from pathlib import Path

CATALOGUE = Path(__file__).resolve().parents[1] / 'public-demo-catalogue.json'

def seed_public_catalogue(db):
    if not CATALOGUE.exists():
        return
    data = json.loads(CATALOGUE.read_text(encoding='utf-8'))
    if data.get('format') != 'lapeng-public-business-catalogue-v1':
        raise ValueError('Unsupported public demo catalogue format')
    # Stable catalogue identifiers survive repeated bootstraps in the same DB.
    db.execute('CREATE TABLE IF NOT EXISTS demo_catalogue_entries (catalogue_key TEXT PRIMARY KEY, provider_id INTEGER NOT NULL REFERENCES providers(id), listing_id INTEGER REFERENCES listings(id))')
    for business in data['businesses']:
        name = str(business['name']).strip()
        key = 'business:' + name.casefold()
        row = db.execute('SELECT provider_id FROM demo_catalogue_entries WHERE catalogue_key=?', (key,)).fetchone()
        if row and db.execute('SELECT 1 FROM providers WHERE id=?',(row[0],)).fetchone():
            pid=row[0]
        else:
            # Do not claim any real user's business, impersonate an account, or alter verified status.
            cur=db.execute('''INSERT INTO providers(owner_id,name,category,kind,city,country,remote,bio,skills,price,capacity,rating,reviews,verified,featured,website,service_radius_km)
              VALUES(NULL,?,?,?,?,?,?,?,?,?, ?,0,0,0,0,?,?)''',
              (name,business['category'],business['kind'],business['city'],business['country'],int(bool(business['remote'])),business['bio'],business['skills'],int(business['price']),int(business['capacity']),business.get('website') or '',int(business.get('service_radius_km') or 25)))
            pid=cur.lastrowid
            db.execute('INSERT OR REPLACE INTO demo_catalogue_entries(catalogue_key,provider_id,listing_id) VALUES(?,?,NULL)',(key,pid))
        for item in business['listings']:
            lk=key+'|listing:'+item['title'].strip().casefold()
            already=db.execute('SELECT listing_id FROM demo_catalogue_entries WHERE catalogue_key=?',(lk,)).fetchone()
            if already and already[0] and db.execute('SELECT 1 FROM listings WHERE id=?',(already[0],)).fetchone():
                continue
            cur=db.execute('''INSERT INTO listings(provider_id,title,description,price,kind,stock,catalog_category,specs_json,variants_json,packages_json,fulfilment_json,currency)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                (pid,item['title'],item['description'],int(item['price']),item['kind'],int(item['stock']),item.get('catalog_category') or '',item.get('specs_json') or '{}',item.get('variants_json') or '[]',item.get('packages_json') or '[]',item.get('fulfilment_json') or '{}',item.get('currency') or 'USD'))
            db.execute('INSERT OR REPLACE INTO demo_catalogue_entries(catalogue_key,provider_id,listing_id) VALUES(?,?,?)',(lk,pid,cur.lastrowid))
