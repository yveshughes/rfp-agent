import io
import json
import os
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from fastapi import UploadFile, HTTPException
from PIL import Image, ImageDraw, ImageFont
os.environ.setdefault('BILLY_DATA_DIR',tempfile.mkdtemp(prefix='billy-attachment-test-'))
from app import server
from app.company_attachments import extract_text, recognize_image

class CompanyAttachmentTests(unittest.IsolatedAsyncioTestCase):
    async def upload(self,name,raw):
        return await server.company_attachment(UploadFile(filename=name,file=io.BytesIO(raw)))

    async def test_text_original_dedup_and_metadata(self):
        raw=b'Our company installs commercial lighting.\nLicensed electrical contractor.'
        result=await self.upload('company.txt',raw)
        again=await self.upload('renamed.txt',raw)
        self.assertEqual(result['id'],again['id']);self.assertTrue(again['existing'])
        doc=await server.get_document(result['id'])
        self.assertIsNone(doc['rfp_id']);self.assertEqual(doc['pages'][0]['text'],raw.decode())
        self.assertIn('not original page numbers',doc['extraction_note'])
        original=await server.original_document(result['id'])
        self.assertEqual(original.path.read_bytes(),raw)
        self.assertIn('attachment',original.headers['content-disposition'])
        with self.assertRaises(HTTPException):await server.document_preview(result['id'])
        with self.assertRaises(HTTPException):await server.original_document('../secret')

    async def test_invalid_types_and_content_are_rejected(self):
        for name,raw in [('unsafe.html',b'<script>'),('empty.txt',b''),('fake.png',b'not an image'),('bad.docx',b'broken zip'),('binary.txt',b'\x00')]:
            with self.subTest(name=name),self.assertRaises(HTTPException) as error:await self.upload(name,raw)
            self.assertEqual(error.exception.status_code,400)
        with patch('app.company_attachments.MAX_BYTES',3):
            with self.assertRaises(HTTPException) as error:await self.upload('big.txt',b'1234')
            self.assertEqual(error.exception.status_code,413)

    async def test_image_original_preview_and_empty_text(self):
        output=io.BytesIO();Image.new('RGB',(100,50),'white').save(output,'PNG');raw=output.getvalue()
        with patch('app.company_attachments.shutil.which',return_value=None):result=await self.upload('image.png',raw)
        self.assertEqual(result['media_type'],'image/png')
        doc=await server.get_document(result['id']);self.assertEqual(doc['pages'][0]['text'],'')
        self.assertIn('unavailable',doc['extraction_note'])
        original=await server.original_document(result['id']);self.assertEqual(original.path.read_bytes(),raw)
        self.assertIn('inline',original.headers['content-disposition'])
        preview=await server.document_preview(result['id']);self.assertTrue(preview.path.read_bytes().startswith(b'\x89PNG'))

    async def test_docx_extracts_tables_and_rejects_unsafe_xml(self):
        def word(xml):
            output=io.BytesIO()
            with zipfile.ZipFile(output,'w') as z:z.writestr('word/document.xml',xml)
            return output.getvalue()
        raw=word('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Licensed contractor</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>Lighting work</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>')
        result=await self.upload('capabilities.docx',raw)
        doc=await server.get_document(result['id'])
        self.assertEqual(doc['pages'][0]['text'],'Licensed contractor\nLighting work')
        with self.assertRaises(ValueError):extract_text(word('<!DOCTYPE foo><foo/>'),'.docx')
        pages,note=extract_text(b'x'*600001,'.txt');self.assertEqual(len(pages),60);self.assertIn('first 600,000',note)

    async def test_quoted_csv_excerpts_fit_agent_serialization_limit(self):
        raw=('"a","b","c"\n'*5000).encode()
        pages,_=extract_text(raw,'.csv')
        self.assertEqual(''.join(p['text'] for p in pages),raw.decode())
        self.assertTrue(all(len(json.dumps({'pages':[p]},ensure_ascii=False))<64000 for p in pages))
