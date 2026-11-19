# main/test_documents.py
"""Тесты ЛЗ 13: чтение PDF и Word и вывод содержимого на странице."""
import io
import zipfile
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse
from docx import Document
from PIL import Image

from . import documents


def png_bytes(size=(60, 60), color=(200, 30, 30)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def make_docx(heading="Report title", paragraph="First paragraph of the report.", table=None, bullet=None, picture=False):
    doc = Document()
    doc.add_heading(heading, level=1)
    doc.add_paragraph(paragraph)
    if bullet:
        doc.add_paragraph(bullet, style="List Bullet")
    if picture:
        doc.add_picture(io.BytesIO(png_bytes()))
        doc.add_paragraph("Text after the picture.")
    if table:
        t = doc.add_table(rows=len(table), cols=len(table[0]))
        t.style = "Table Grid"
        for i, row in enumerate(table):
            for j, value in enumerate(row):
                t.cell(i, j).text = value
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def make_pdf(title="Report title", paragraph="First paragraph of the report.", table=None, picture=False, extra=()):
    """Маленький настоящий PDF руками: заголовок, абзац и таблица из прямоугольников."""
    parts = [f"BT /F1 20 Tf 72 740 Td ({title}) Tj ET", f"BT /F1 11 Tf 72 700 Td ({paragraph}) Tj ET"]
    y = 640
    for row in (table or []):
        for j, value in enumerate(row):
            x = 72 + j * 120
            parts.append(f"{x} {y} 120 30 re S")
            parts.append(f"BT /F1 10 Tf {x + 8} {y + 10} Td ({value}) Tj ET")
        y -= 30
    parts.extend(extra)
    if picture:                         # квадрат 200x200 пунктов, картинка 2x2 пикселя из сырых RGB-байтов
        parts.append("q 200 0 0 200 72 400 cm /Im1 Do Q")
    stream = "\n".join(parts).encode("latin-1")
    resources = "/Font << /F1 4 0 R >>" + (" /XObject << /Im1 6 0 R >>" if picture else "")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 5 0 R /Resources << " + resources.encode() + b" >> >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
    ]
    if picture:
        raw = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 0])
        objs.append(b"<< /Type /XObject /Subtype /Image /Width 2 /Height 2 /ColorSpace /DeviceRGB "
                    b"/BitsPerComponent 8 /Length 12 >>\nstream\n" + raw + b"\nendstream")
    out, offsets = b"%PDF-1.4\n", []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return out


TABLE = [["Name", "Score"], ["Alice", "90"], ["Bob", "75"]]


class DocumentsBase(TestCase):
    def setUp(self):
        User.objects.create_user("stud", "s@e.kz", "pass12345!")
        self.client.login(username="stud", password="pass12345!")
        self.url = reverse("document_view")

    def upload(self, name, data, client=None):
        return (client or self.client).post(self.url, {"file": SimpleUploadedFile(name, data)})


class ReaderTests(TestCase):
    def read(self, name, data):
        return documents.read_document(SimpleUploadedFile(name, data))

    def test_docx_blocks_in_order(self):
        doc = self.read("a.docx", make_docx(table=TABLE, bullet="Point one"))
        kinds = [b.kind for b in doc.pages[0].blocks]
        self.assertEqual(kinds, ["heading", "paragraph", "bullet", "table"])
        self.assertEqual(doc.pages[0].blocks[0].text, "Report title")
        self.assertEqual(doc.pages[0].blocks[3].rows, TABLE)
        self.assertFalse(doc.is_pdf)

    def test_pdf_text_and_table(self):
        doc = self.read("a.pdf", make_pdf(table=TABLE))
        self.assertTrue(doc.is_pdf)
        self.assertEqual(len(doc.pages), 1)
        texts = [b.text for b in doc.pages[0].blocks if b.kind != "table"]
        self.assertTrue(any("Report title" in t for t in texts))
        self.assertTrue(any("First paragraph" in t for t in texts))
        tables = [b for b in doc.pages[0].blocks if b.kind == "table"]
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0].rows, TABLE)

    def test_unsupported_extension(self):
        with self.assertRaises(documents.DocumentError):
            self.read("a.txt", b"hello")

    def test_broken_files_give_document_error(self):
        for name, data in (("a.pdf", b"%PDF-1.4 garbage"), ("a.docx", b"PK\x03\x04 garbage")):
            with self.assertRaises(documents.DocumentError, msg=name):
                self.read(name, data)

    def test_zip_bomb_is_rejected(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("word/document.xml", b"0" * (documents.MAX_UNPACKED + 1024))
        with self.assertRaises(documents.DocumentError):
            self.read("bomb.docx", buf.getvalue())


class PageTests(DocumentsBase):
    def test_login_required(self):
        anon = Client()
        r = anon.get(self.url)
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("login"), r["Location"])
        self.assertEqual(anon.post(self.url, {}).status_code, 302)

    def test_form_is_shown(self):
        r = self.client.get(self.url)
        self.assertContains(r, 'enctype="multipart/form-data"')
        self.assertContains(r, "csrfmiddlewaretoken")
        self.assertNotContains(r, 'id="document-result"')

    def test_docx_is_rendered_with_table(self):
        r = self.upload("report.docx", make_docx(table=TABLE))
        self.assertContains(r, "Report title")
        self.assertContains(r, "First paragraph of the report.")
        self.assertContains(r, "<table")
        for cell in ("Name", "Score", "Alice", "90", "Bob", "75"):
            self.assertContains(r, f">{cell}</t")
        self.assertContains(r, "report.docx")

    def test_pdf_is_rendered_with_page_and_table(self):
        r = self.upload("report.pdf", make_pdf(table=TABLE))
        self.assertContains(r, "Report title")
        self.assertContains(r, "Страница 1")
        self.assertContains(r, "<table")
        self.assertContains(r, ">Alice</td>")

    def test_wrong_type_is_rejected_with_message(self):
        for name in ("evil.exe", "notes.txt", "pic.png"):
            r = self.upload(name, b"data")
            self.assertEqual(r.status_code, 200, msg=name)
            self.assertContains(r, "Допустимы только PDF и Word")
            self.assertNotContains(r, 'id="document-result"')

    def test_old_doc_format_has_hint(self):
        self.assertContains(self.upload("old.doc", b"data"), "сохраните файл как .docx")

    def test_fake_extension_is_detected_by_content(self):
        self.assertContains(self.upload("fake.pdf", b"just text"), "не похож на PDF")
        self.assertContains(self.upload("fake.docx", b"just text"), "не похож на документ Word")

    def test_too_big_file_is_rejected(self):
        with mock.patch.object(documents, "MAX_SIZE", 100):
            r = self.upload("big.pdf", make_pdf())
        self.assertContains(r, "Файл больше")

    def test_broken_file_gives_message_not_500(self):
        r = self.upload("broken.docx", b"PK\x03\x04 garbage")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Не удалось открыть Word")

    def test_document_text_is_escaped(self):
        """Текст из документа выводится экранированным: <script> из файла не выполнится."""
        r = self.upload("x.docx", make_docx(paragraph="<script>alert('XSS')</script>", table=[["<b>x</b>", "y"]]))
        self.assertNotContains(r, "<script>alert")
        self.assertContains(r, "&lt;script&gt;alert(")
        self.assertContains(r, "&lt;b&gt;x&lt;/b&gt;")

    def test_upload_without_csrf_token_is_forbidden(self):
        strict = Client(enforce_csrf_checks=True)
        strict.login(username="stud", password="pass12345!")
        r = self.upload("report.docx", make_docx(), client=strict)
        self.assertEqual(r.status_code, 403)

    def test_empty_pdf_shows_hint(self):
        r = self.upload("empty.pdf", make_pdf(title="", paragraph=""))
        self.assertContains(r, "не найден текст")

    def test_menu_has_link(self):
        self.assertContains(self.client.get(reverse("slot_list")), reverse("document_view"))


class ImageTests(DocumentsBase):
    """Картинки внутри документов: показываем как <img>, лишнее (фон, значки, лимиты) отсекаем."""

    def test_docx_picture_is_read_in_place(self):
        doc = documents.read_document(SimpleUploadedFile("p.docx", make_docx(picture=True)))
        kinds = [b.kind for b in doc.pages[0].blocks]
        self.assertEqual(kinds, ["heading", "paragraph", "image", "paragraph"])   # картинка стоит между абзацами
        self.assertEqual(doc.images_count, 1)
        self.assertTrue(doc.pages[0].blocks[2].src.startswith("data:image/jpeg;base64,"))

    def test_pdf_picture_is_read(self):
        doc = documents.read_document(SimpleUploadedFile("p.pdf", make_pdf(picture=True)))
        self.assertEqual(doc.images_count, 1)

    def test_images_are_rendered_as_img_tag(self):
        r = self.upload("p.docx", make_docx(picture=True))
        self.assertContains(r, '<img src="data:image/jpeg;base64,')
        self.assertContains(r, "картинок: 1")

    def test_pdf_without_pictures_has_none(self):
        self.assertEqual(documents.read_document(SimpleUploadedFile("p.pdf", make_pdf())).images_count, 0)

    def test_image_limit_is_respected(self):
        with mock.patch.object(documents, "MAX_IMAGES", 0):
            doc = documents.read_document(SimpleUploadedFile("p.docx", make_docx(picture=True)))
        self.assertEqual((doc.images_count, doc.skipped_images), (0, 1))

    def test_broken_picture_is_skipped_not_crash(self):
        with mock.patch.object(documents.Image, "open", side_effect=OSError("bad image")):
            doc = documents.read_document(SimpleUploadedFile("p.docx", make_docx(picture=True)))
        self.assertEqual(doc.images_count, 0)


class ColumnTests(TestCase):
    def test_two_columns_are_read_column_by_column(self):
        lines = []
        for i, (left, right) in enumerate([("Left one", "Right one"), ("Left two", "Right two"), ("Left three", "Right three")]):
            y = 600 - i * 30
            lines += [f"BT /F1 11 Tf 72 {y} Td ({left}) Tj ET", f"BT /F1 11 Tf 380 {y} Td ({right}) Tj ET"]
        doc = documents.read_document(SimpleUploadedFile("c.pdf", make_pdf(title="Title", paragraph="Intro", extra=lines)))
        text = " ".join(b.text for b in doc.pages[0].blocks)
        self.assertLess(text.index("Left three"), text.index("Right one"))   # сначала вся левая колонка

    def test_single_column_text_is_unchanged(self):
        doc = documents.read_document(SimpleUploadedFile("c.pdf", make_pdf()))
        self.assertEqual([b.kind for b in doc.pages[0].blocks], ["heading", "paragraph"])
