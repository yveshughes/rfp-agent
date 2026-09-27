"""Workspace-local company attachments, preserving originals and readable evidence."""
import asyncio
import hashlib
import io
import json
import os
import shutil
import tempfile
import time
import uuid
import zipfile
from pathlib import Path
from xml.etree import ElementTree
from PIL import Image, ImageOps
from fastapi import File, UploadFile, HTTPException
from fastapi.responses import FileResponse

FORMATS={'.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp','.docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document','.txt':'text/plain','.csv':'text/csv','.md':'text/plain'}
MAX_BYTES=25*1024*1024
TEXT_CHUNK=10000

def text_pages(text):
    # At most 60k serialized characters even for JSON-escaped control text.
    return [{'page':n//TEXT_CHUNK+1,'text':text[n:n+TEXT_CHUNK]} for n in range(0,len(text),TEXT_CHUNK)] or [{'page':1,'text':''}]



def original_path(data,row):
    ext=dict(row).get('file_ext') or '.pdf'
    if ext not in {'.pdf',*FORMATS}:raise HTTPException(404)
    return data/(row['id']+ext)


def extract_text(raw,ext):
    if ext=='.docx':
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                entries=archive.infolist()
                if len(entries)>1000 or sum(e.file_size for e in entries)>30*1024*1024:raise ValueError('Document is too large to extract.')
                if any('vbaproject' in e.filename.lower() for e in entries):raise ValueError('Macro-enabled files are not supported.')
                xml=archive.read('word/document.xml')
                if b'<!DOCTYPE' in xml or b'<!ENTITY' in xml:raise ValueError('Unsupported document structure.')
                root=ElementTree.fromstring(xml)
                ns='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
                text='\n'.join(''.join(p.itertext()) for p in root.iter(ns+'p'))
        except (zipfile.BadZipFile,KeyError,ElementTree.ParseError,RuntimeError,NotImplementedError) as exc:raise ValueError('Choose a valid Word .docx document.') from exc
    else:
        try:text=raw.decode('utf-8-sig')
        except UnicodeDecodeError as exc:raise ValueError('Save this text file as UTF-8 before attaching it.') from exc
        if '\x00' in text:raise ValueError('This does not appear to be a text file.')
    note='Extracted text; section numbers are excerpts, not original page numbers.'
    if len(text)>600000:note+=' Only the first 600,000 characters were extracted; the full original is retained.'
    text=text[:600000]
    return text_pages(text),note


def image_for_ocr(raw,ext,destination):
    with Image.open(io.BytesIO(raw)) as image:
        expected={'.png':'PNG','.jpg':'JPEG','.jpeg':'JPEG','.webp':'WEBP'}[ext]
        if image.format!=expected:raise ValueError('The image contents do not match its file type.')
        if image.width*image.height>20_000_000:raise ValueError('Choose an image smaller than 20 megapixels.')
        image.load();image=ImageOps.exif_transpose(image).convert('RGB')
        image.thumbnail((3000,3000));image.save(destination,'PNG')


async def recognize_image(raw,ext):
    with tempfile.TemporaryDirectory() as temp:
        source=Path(temp)/'image.png'
        try:await asyncio.to_thread(image_for_ocr,raw,ext,source)
        except Exception as exc:raise HTTPException(400,str(exc) if isinstance(exc,ValueError) else 'Choose a valid PNG, JPG or WebP image.') from None
        renderer=shutil.which('tesseract')
        if not renderer:return [{'page':1,'text':''}],'Original image saved. Text recognition is unavailable.'
        process=await asyncio.create_subprocess_exec(renderer,str(source),str(Path(temp)/'text'),'-l','eng',stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL,env={**os.environ,'OMP_THREAD_LIMIT':'1'})
        try:await asyncio.wait_for(process.wait(),timeout=25)
        except (asyncio.TimeoutError,asyncio.CancelledError) as exc:
            if process.returncode is None:process.kill()
            await process.wait()
            if isinstance(exc,asyncio.CancelledError):raise
            return [{'page':1,'text':''}],'Original image saved. Text recognition timed out.'
        output=Path(temp)/'text.txt'
        text=output.read_text(errors='replace')[:60000] if process.returncode==0 and output.exists() else ''
        return text_pages(text),('Text recognized from image; excerpt numbers are not original pages. Confirm exact wording against the original.' if text.strip() else 'No readable text found. Original image saved for review.')


def register_company_attachments(app,db,data,store_pdf,event,document_work):
    importing=asyncio.Lock()

    @app.post('/api/company/attachments')
    async def upload(file:UploadFile=File(...)):
        name=Path((file.filename or 'attachment').replace('\\','/')).name[:200]
        ext=Path(name).suffix.lower()
        if ext not in {'.pdf',*FORMATS}:raise HTTPException(400,'Choose a PDF, PNG, JPG, WebP, DOCX, TXT, CSV or Markdown file.')
        raw=await file.read(MAX_BYTES+1)
        if len(raw)>MAX_BYTES:raise HTTPException(413,'Each attachment must be 25 MB or smaller.')
        if not raw:raise HTTPException(400,'This file is empty.')
        async with importing,document_work():
            if ext=='.pdf':
                result=await store_pdf(raw,name,automatic=True)
            else:
                media=FORMATS[ext];digest=hashlib.sha256(raw).hexdigest()
                with db() as c:duplicate=c.execute('SELECT id FROM documents WHERE sha256=? AND rfp_id IS NULL AND media_type=?',(digest,media)).fetchone()
                if duplicate:result={'id':duplicate['id'],'existing':True}
                else:
                    if media.startswith('image/'):pages,note=await recognize_image(raw,ext)
                    else:
                        try:pages,note=await asyncio.to_thread(extract_text,raw,ext)
                        except ValueError as exc:raise HTTPException(400,str(exc)) from None
                    doc_id=uuid.uuid4().hex;path=data/(doc_id+ext);path.write_bytes(raw)
                    try:
                        with db() as c:c.execute('INSERT INTO documents(id,name,first_page,last_page,added,pages,rfp_id,sha256,total_pages,media_type,file_ext,extraction_note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(doc_id,name,1,len(pages),time.time(),json.dumps(pages),None,digest,len(pages),media,ext,note))
                    except Exception:path.unlink(missing_ok=True);raise
                    event('done','Company attachment saved',name)
                    result={'id':doc_id,'existing':False}
            with db() as c:row=c.execute('SELECT id,name,media_type,extraction_note FROM documents WHERE id=?',(result['id'],)).fetchone()
            return {**result,**dict(row)}

    @app.get('/api/documents/{doc_id}/file')
    async def original(doc_id:str,download:bool=False):
        if len(doc_id)!=32 or any(ch not in '0123456789abcdef' for ch in doc_id):raise HTTPException(404)
        with db() as c:row=c.execute('SELECT * FROM documents WHERE id=?',(doc_id,)).fetchone()
        if not row:raise HTTPException(404)
        path=original_path(data,row)
        if not path.is_file():raise HTTPException(404)
        media=row['media_type'] or 'application/pdf'
        inline=not download and (media=='application/pdf' or media.startswith('image/'))
        return FileResponse(path,media_type=media,filename=row['name'],content_disposition_type='inline' if inline else 'attachment',headers={'X-Content-Type-Options':'nosniff','Cache-Control':'private, max-age=86400'})
    return upload,original
