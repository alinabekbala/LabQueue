# main/documents.py
"""Чтение документов PDF и Word (ЛЗ 13).

Это «модель» нашей функции: обычный Python без привязки к вебу. Принимает файл,
возвращает структуру «страницы → блоки (заголовок, абзац, таблица)».
View и шаблон ничего не знают про библиотеки: pdfplumber (PDF) и python-docx (Word).
Файл читается в памяти и нигде не сохраняется.
"""
import io
import os
import zipfile
from dataclasses import dataclass, field
from statistics import median

import pdfplumber
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

MAX_SIZE = 5 * 1024 * 1024          # максимальный размер загружаемого файла
MAX_PDF_PAGES = 40                  # защита от слишком больших документов
MAX_UNPACKED = 50 * 1024 * 1024     # защита от «бомбы» в .docx (это zip-архив)
ALLOWED = {".pdf": "PDF", ".docx": "Word"}


class DocumentError(Exception):
    """Понятная пользователю причина, почему файл не удалось прочитать."""


@dataclass
class Block:
    kind: str                       # "heading" | "paragraph" | "bullet" | "table"
    text: str = ""
    level: int = 0                  # уровень заголовка (1–3)
    rows: list = field(default_factory=list)   # строки таблицы: список списков строк


@dataclass
class Page:
    number: int | None              # номер страницы (у Word страниц нет)
    blocks: list = field(default_factory=list)


@dataclass
class ParsedDocument:
    kind: str                       # "PDF" или "Word"
    name: str
    pages: list = field(default_factory=list)

    @property
    def is_pdf(self):
        return self.kind == "PDF"

    @property
    def blocks_count(self):
        return sum(len(p.blocks) for p in self.pages)

    @property
    def tables_count(self):
        return sum(1 for p in self.pages for b in p.blocks if b.kind == "table")

    @property
    def chars_count(self):
        total = 0
        for p in self.pages:
            for b in p.blocks:
                total += len(b.text) + sum(len(c) for r in b.rows for c in r)
        return total


# ---------- PDF (pdfplumber) ----------
def _clean_cell(value):
    return (value or "").replace("\r", "").strip()


def _clean_table(rows):
    """Убираем пустые строки и столбцы, None заменяем пустой строкой."""
    cleaned = [[_clean_cell(c) for c in row] for row in rows]
    cleaned = [r for r in cleaned if any(r)]
    if not cleaned:
        return []
    width = max(len(r) for r in cleaned)
    cleaned = [r + [""] * (width - len(r)) for r in cleaned]
    keep = [i for i in range(width) if any(r[i] for r in cleaned)]
    return [[r[i] for i in keep] for r in cleaned]


def _outer_tables(tables):
    """Оставляем только внешние таблицы: вложенные (внутри другой таблицы) pdfplumber находит как отдельные, это шум."""
    def inside(a, b):
        return a is not b and a.bbox[0] >= b.bbox[0] - 2 and a.bbox[1] >= b.bbox[1] - 2 \
            and a.bbox[2] <= b.bbox[2] + 2 and a.bbox[3] <= b.bbox[3] + 2
    return [t for t in tables if not any(inside(t, other) for other in tables)]


def _text_blocks(page, top, bottom, body_size):
    """Текст страницы между двумя высотами: абзацы и заголовки (по размеру шрифта и интервалам)."""
    top, bottom = max(top, 0), min(bottom, page.height)
    if bottom - top < 3:
        return []
    region = page.crop((0, top, page.width, bottom))
    blocks, current, prev, current_heading = [], [], None, False

    def flush():
        nonlocal current, current_heading
        text = " ".join(current).strip()
        if text:
            blocks.append(Block("heading", text, level=2) if current_heading else Block("paragraph", text))
        current, current_heading = [], False

    for line in region.extract_text_lines(return_chars=True):
        text = line["text"].strip()
        if not text:
            continue
        sizes = [c["size"] for c in line["chars"] if c["text"].strip()]
        size = median(sizes) if sizes else body_size
        heading = size >= body_size * 1.15 and len(text) < 160
        gap = (line["top"] - prev["bottom"]) if prev else 0
        height = max(line["bottom"] - line["top"], 1)
        # новый блок: большой интервал, смена «заголовок/текст» или предыдущая строка закончилась точкой
        if current and (gap > height * 0.6 or heading != current_heading):
            flush()
        current.append(text)
        current_heading = heading
        prev = line
    flush()
    return blocks


def read_pdf(file, name="document.pdf"):
    try:
        pdf = pdfplumber.open(file)
    except Exception as exc:                    # повреждённый или зашифрованный файл
        raise DocumentError("Не удалось открыть PDF: файл повреждён или защищён паролем.") from exc
    pages = []
    with pdf:
        if len(pdf.pages) > MAX_PDF_PAGES:
            raise DocumentError(f"В PDF слишком много страниц (максимум {MAX_PDF_PAGES}).")
        for number, page in enumerate(pdf.pages, start=1):
            try:
                sizes = [c["size"] for c in page.chars if c["text"].strip()]
                body_size = median(sizes) if sizes else 10
                blocks, top = [], 0
                for table in sorted(_outer_tables(page.find_tables()), key=lambda t: t.bbox[1]):
                    blocks += _text_blocks(page, top, table.bbox[1], body_size)
                    rows = _clean_table(table.extract())
                    if rows:
                        blocks.append(Block("table", rows=rows))
                    top = table.bbox[3]
                blocks += _text_blocks(page, top, page.height, body_size)
            except Exception as exc:
                raise DocumentError(f"Не удалось прочитать страницу {number} PDF.") from exc
            pages.append(Page(number, blocks))
    return ParsedDocument("PDF", name, pages)


# ---------- Word (python-docx) ----------
def _heading_level(style_name):
    name = (style_name or "").lower()
    if name == "title" or name == "название":
        return 1
    for prefix in ("heading", "заголовок"):
        if name.startswith(prefix):
            digits = "".join(ch for ch in name if ch.isdigit())
            return min(int(digits), 3) if digits else 2
    return 0


def _docx_table(table):
    rows = []
    for row in table.rows:
        cells, last = [], None
        for cell in row.cells:
            if cell._tc is last:            # объединённая ячейка повторяется: берём один раз
                continue
            last = cell._tc
            cells.append(_clean_cell(cell.text))
        rows.append(cells)
    return _clean_table(rows)


def read_docx(file, name="document.docx"):
    try:
        with zipfile.ZipFile(file) as archive:
            if sum(i.file_size for i in archive.infolist()) > MAX_UNPACKED:
                raise DocumentError("Файл слишком большой после распаковки.")
        file.seek(0)
        document = Document(file)
    except DocumentError:
        raise
    except Exception as exc:
        raise DocumentError("Не удалось открыть Word: файл повреждён или это не .docx.") from exc

    blocks = []
    for child in document.element.body.iterchildren():
        if child.tag.endswith("}p"):
            paragraph = Paragraph(child, document)
            text = paragraph.text.strip()
            if not text:
                continue
            style = paragraph.style.name if paragraph.style is not None else ""
            level = _heading_level(style)
            if level:
                blocks.append(Block("heading", text, level=level))
            elif style.lower().startswith(("list", "список")):
                blocks.append(Block("bullet", text))
            else:
                blocks.append(Block("paragraph", text))
        elif child.tag.endswith("}tbl"):
            rows = _docx_table(Table(child, document))
            if rows:
                blocks.append(Block("table", rows=rows))
    return ParsedDocument("Word", name, [Page(None, blocks)])


# ---------- Общая точка входа ----------
def read_document(uploaded):
    """Определяет формат по расширению и читает файл. Бросает DocumentError с понятным текстом."""
    ext = os.path.splitext(uploaded.name)[1].lower()
    uploaded.seek(0)
    data = io.BytesIO(uploaded.read())
    if ext == ".pdf":
        return read_pdf(data, uploaded.name)
    if ext == ".docx":
        return read_docx(data, uploaded.name)
    raise DocumentError("Поддерживаются только PDF и Word (.docx).")
