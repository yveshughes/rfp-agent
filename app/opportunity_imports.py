"""Shared, reversible opportunity catalog with private company pursuit records."""
import hashlib
import json
import time
import uuid
from urllib.parse import urlsplit
from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator
from app.opportunities import canonical

class ImportedOpportunity(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default='', max_length=10000)
    url: str = Field(max_length=3000)
    agencies: list[str] = Field(default_factory=list, max_length=20)
    source_ids: list[int] = Field(default_factory=list, max_length=20)
    kind: str = Field(default='solicitation', max_length=50)
    status: str = Field(default='unknown', pattern='^(open|closed|unknown)$')
    description_quality: str = Field(default='missing', max_length=80)
    quality_notes: list[str] = Field(default_factory=list, max_length=30)
    checked_at: str = Field(default='', max_length=80)
    listing_url: str = Field(default='', max_length=3000)
    attachment_only: bool = False

    @field_validator('url','listing_url')
    @classmethod
    def valid_link(cls,value):
        if not value:return value
        try:
            p=urlsplit(value)
            if p.scheme not in ('http','https') or not p.hostname or p.username or p.password or p.port not in (None,80,443):raise ValueError()
        except ValueError:raise ValueError('Use an HTTP(S) source link without credentials.')
        return value

    @field_validator('title')
    @classmethod
    def valid_title(cls,value):
        if not value.strip():raise ValueError('Title is required.')
        return value.strip()

class OpportunityImport(BaseModel):
    label: str = Field(min_length=1,max_length=120)
    rows: list[ImportedOpportunity] = Field(min_length=1,max_length=1000)

class ImportVisibility(BaseModel):
    active: bool


def register_imports(app,db,catalog_db):
    # The catalog connection is shared by every workspace on this server.
    with catalog_db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS catalog_batches(id TEXT PRIMARY KEY,label TEXT,created REAL,active INTEGER,digest TEXT UNIQUE,skipped INTEGER);
        CREATE TABLE IF NOT EXISTS catalog_items(id TEXT PRIMARY KEY,batch_id TEXT,url_key TEXT UNIQUE,metadata TEXT);
        CREATE INDEX IF NOT EXISTS catalog_batch_items ON catalog_items(batch_id);
        ''')
    with db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS opportunity_catalog_links(rfp_id TEXT,catalog_id TEXT PRIMARY KEY,created_by_catalog INTEGER)')

    def snapshot():
        with catalog_db() as c:
            c.execute('BEGIN')
            batches=[dict(r) for r in c.execute('''SELECT b.*,
                (SELECT COUNT(*) FROM catalog_items i WHERE i.batch_id=b.id) AS imported
                FROM catalog_batches b ORDER BY b.created DESC''')]
            items=[dict(r) for r in c.execute('SELECT i.*,b.label,b.active FROM catalog_items i JOIN catalog_batches b ON b.id=i.batch_id')]
        return batches,items

    def sync():
        batches,items=snapshot()
        now=time.time();result={}
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            links={r['catalog_id']:dict(r) for r in c.execute('SELECT * FROM opportunity_catalog_links')}
            existing={canonical(r['url']):r['id'] for r in c.execute('SELECT id,url FROM rfps') if r['url']}
            existing.update({canonical(r['listing_url']):r['rfp_id'] for r in c.execute('SELECT * FROM opportunity_sources') if r['listing_url']})
            for item in items:
                row=json.loads(item['metadata']);link=links.get(item['id'])
                if not link and item['active']:
                    rid=existing.get(item['url_key']);owned=not bool(rid)
                    if owned:
                        rid=uuid.uuid4().hex
                        notes='Shared catalog candidate; verify the original source before acting.\n\n'+row['description']
                        notes+='\n\nDescription quality: '+row['description_quality']+'\n'+'\n'.join(row['quality_notes'])
                        c.execute('INSERT INTO rfps VALUES (?,?,?,?,?,?,?,?,?)',(rid,row['title'],'; '.join(row['agencies']),row['url'],'Researching','',notes[:10000],now,now))
                        c.execute('INSERT INTO discovered_rfps VALUES (?,0)',(rid,))
                        c.execute('INSERT INTO opportunity_reviews(rfp_id,body,reviewed,error,complete) VALUES (?,?,NULL,?,0)',(rid,row['description'],'Imported webpage evidence; source and availability not verified.'))
                        existing[item['url_key']]=rid
                    c.execute('INSERT INTO opportunity_catalog_links VALUES (?,?,?)',(rid,item['id'],int(owned)))
                    link={'rfp_id':rid,'created_by_catalog':int(owned)}
                if link:
                    previous=result.get(link['rfp_id'])
                    current={**row,'batch_id':item['batch_id'],'label':item['label'],'active':bool(item['active']),'created_by_catalog':link['created_by_catalog']}
                    if previous:
                        chosen=previous if previous['active'] else current
                        current={**chosen,'active':previous['active'] or current['active'],'created_by_catalog':previous['created_by_catalog'] or current['created_by_catalog']}
                    result[link['rfp_id']]=current
        return result,batches

    @app.get('/api/opportunity-imports')
    async def batches():
        rows,_=snapshot()
        return {'batches':rows,'scope':'shared_catalog'}

    @app.post('/api/opportunity-imports')
    async def import_batch(req:OpportunityImport):
        payload=[row.model_dump() for row in req.rows]
        digest=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
        now=time.time();batch_id=uuid.uuid4().hex;skipped=0
        with catalog_db() as c:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute('SELECT id FROM catalog_batches WHERE digest=?',(digest,)).fetchone()
            if old:return {'id':old['id'],'existing':True,'scope':'shared_catalog'}
            existing={r['url_key'] for r in c.execute('SELECT url_key FROM catalog_items')}
            c.execute('INSERT INTO catalog_batches VALUES (?,?,?,?,?,?)',(batch_id,req.label.strip(),now,1,digest,0))
            for row in payload:
                key=canonical(row['url'])
                if key in existing:skipped+=1;continue
                existing.add(key)
                c.execute('INSERT INTO catalog_items VALUES (?,?,?,?)',(uuid.uuid4().hex,batch_id,key,json.dumps(row)))
            c.execute('UPDATE catalog_batches SET skipped=? WHERE id=?',(skipped,batch_id))
        return {'id':batch_id,'imported':len(payload)-skipped,'skipped':skipped,'existing':False,'scope':'shared_catalog'}

    @app.post('/api/opportunity-imports/{batch_id}/visibility')
    async def visibility(batch_id:str,req:ImportVisibility):
        with catalog_db() as c:
            if not c.execute('SELECT 1 FROM catalog_batches WHERE id=?',(batch_id,)).fetchone():raise HTTPException(404,'Import batch not found.')
            c.execute('UPDATE catalog_batches SET active=? WHERE id=?',(int(req.active),batch_id))
        return {'id':batch_id,'active':req.active,'scope':'shared_catalog'}

    return batches,import_batch,visibility,sync
