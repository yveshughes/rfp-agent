"""Render a cached first-page preview of a workspace-owned, saved PDF."""
import asyncio
import shutil
import tempfile
from pathlib import Path
from fastapi import HTTPException
from fastapi.responses import FileResponse
from PIL import Image,ImageOps
from app.company_attachments import original_path


def register_document_previews(app, db, data):
    rendering=asyncio.Lock()

    @app.get('/api/documents/{doc_id}/preview')
    async def preview(doc_id:str):
        if len(doc_id)!=32 or any(ch not in '0123456789abcdef' for ch in doc_id):raise HTTPException(404)
        with db() as c:row=c.execute('SELECT * FROM documents WHERE id=?',(doc_id,)).fetchone()
        if not row:raise HTTPException(404,'Document not found')
        source=original_path(data,row)
        if not source.is_file():raise HTTPException(404,'Document not found')
        media=dict(row).get('media_type') or 'application/pdf'
        if media!='application/pdf' and not media.startswith('image/'):raise HTTPException(404,'No image preview for this file')
        cache=data/'previews';target=cache/f'{doc_id}.png'
        async with rendering:
            if not target.exists():
                if media.startswith('image/'):
                    cache.mkdir(exist_ok=True)
                    def render_image():
                        with Image.open(source) as image:
                            image=ImageOps.exif_transpose(image);image.thumbnail((720,720));image.convert('RGB').save(target,'PNG')
                    try:await asyncio.to_thread(render_image)
                    except Exception:raise HTTPException(422,'Image preview unavailable') from None
                    return FileResponse(target,media_type='image/png',headers={'Cache-Control':'private, max-age=86400'})
                renderer=shutil.which('pdftoppm')
                if not renderer:raise HTTPException(503,'Document preview unavailable')
                cache.mkdir(exist_ok=True)
                with tempfile.TemporaryDirectory(dir=cache) as temp:
                    prefix=Path(temp)/'first-page'
                    process=await asyncio.create_subprocess_exec(renderer,'-f','1','-l','1','-singlefile','-scale-to','720','-png',str(source),str(prefix),stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL)
                    try:await asyncio.wait_for(process.wait(),timeout=15)
                    except (asyncio.TimeoutError,asyncio.CancelledError) as exc:
                        if process.returncode is None:process.kill()
                        await process.wait()
                        if isinstance(exc,asyncio.TimeoutError):raise HTTPException(504,'Document preview unavailable') from None
                        raise
                    image=prefix.with_suffix('.png')
                    if process.returncode or not image.exists() or image.stat().st_size>5*1024*1024:raise HTTPException(422,'Document preview unavailable')
                    image.replace(target)
        return FileResponse(target,media_type='image/png',headers={'Cache-Control':'private, max-age=86400'})
    return preview
