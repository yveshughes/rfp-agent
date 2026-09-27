import asyncio
import io
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from fastapi import FastAPI,HTTPException
from reportlab.pdfgen import canvas
from app.document_previews import register_document_previews

class DocumentPreviewTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.data=Path(self.temp.name);self.conn=sqlite3.connect(':memory:');self.conn.row_factory=sqlite3.Row
        self.conn.execute('CREATE TABLE documents(id TEXT PRIMARY KEY)');self.addCleanup(self.conn.close)
        self.preview=register_document_previews(FastAPI(),lambda:self.conn,self.data)
        self.doc='a'*32
    @unittest.skipUnless(shutil.which('pdftoppm'),'Poppler required')
    async def test_real_first_page_render_cached_and_workspace_scoped(self):
        pdf=io.BytesIO();c=canvas.Canvas(pdf);c.drawString(50,750,'CITY OF TEST — RFP COVER');c.showPage();c.drawString(50,750,'Second page');c.save()
        (self.data/f'{self.doc}.pdf').write_bytes(pdf.getvalue());self.conn.execute('INSERT INTO documents VALUES (?)',(self.doc,))
        first=await self.preview(self.doc);output=Path(first.path)
        self.assertTrue(output.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'))
        modified=output.stat().st_mtime_ns
        responses=await asyncio.gather(self.preview(self.doc),self.preview(self.doc))
        self.assertEqual(output.stat().st_mtime_ns,modified)
        self.assertTrue(all(Path(r.path)==output for r in responses))
        self.conn.execute('DELETE FROM documents')
        with self.assertRaises(HTTPException) as error:await self.preview(self.doc)
        self.assertEqual(error.exception.status_code,404) # Even if the cache exists.
    async def test_invalid_id_and_unknown_document_are_not_rendered(self):
        for doc in ['../secret','a'*32,'z'*32]:
            with self.assertRaises(HTTPException) as error:await self.preview(doc)
            self.assertEqual(error.exception.status_code,404)
