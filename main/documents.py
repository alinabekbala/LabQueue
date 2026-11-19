# main/documents.py
"""Чтение документов PDF и Word (ЛЗ 13).

Это «модель» нашей функции: обычный Python без привязки к вебу. Принимает файл,
возвращает структуру «страницы → блоки (заголовок, абзац, код, таблица)».
View и шаблон ничего не знают про библиотеки: pdfplumber (PDF) и python-docx (Word).
Файл читается в памяти и нигде не сохраняется.
"""
import io
import os
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from statistics import median

import pdfplumber
from docx import Document
from docx.text.paragraph import Paragraph

MAX_SIZE = 5 * 1024 * 1024          # максимальный размер загружаемого файла
MAX_PDF_PAGES = 40                  # защита от слишком больших документов
MAX_UNPACKED = 50 * 1024 * 1024     # защита от «бомбы» в .docx (это zip-архив)
ALLOWED = {".pdf": "PDF", ".docx": "Word"}
MONO_FONTS = ("courier", "consolas", "mono", "menlo", "source code")
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class DocumentError(Exception):
    """Понятная пользователю причина, почему файл не удалось прочитать."""


@dataclass
class Cell:
    text: str = ""
    colspan: int = 1                # ячейка может занимать несколько столбцов и строк
    rowspan: int = 1


@dataclass
class Block:
    kind: str                       # "heading" | "paragraph" | "bullet" | "code" | "table"
    text: str = ""
    level: int = 0                  # уровень заголовка (1–3)
    grid: list = field(default_factory=list)   # таблица: список строк, в строке список Cell

    @property
    def rows(self):
        """Таблица как обычные строки (без объединений): удобно для проверок и подсчёта символов."""
        return [[cell.text for cell in row] for row in self.grid]


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


def _clean(value):
    return (value or "").replace("\r", "").strip()


# ---------- PDF (pdfplumber) ----------
def _cluster(values, tol=2.0):
    """Координаты линий таблицы, которые отличаются меньше чем на tol, считаем одной линией."""
    out = []
    for v in sorted(values):
        if not out or v - out[-1] > tol:
            out.append(v)
    return out


def _nearest(lines, value):
    return min(range(len(lines)), key=lambda i: abs(lines[i] - value))


def _pdf_table(page, table):
    """Таблица как в документе: объединённые ячейки сохраняют colspan и rowspan (по геометрии ячеек)."""
    cells = {tuple(round(v, 1) for v in c) for c in table.cells}
    if not cells:
        return []
    xs = _cluster([c[0] for c in cells] + [c[2] for c in cells])
    ys = _cluster([c[1] for c in cells] + [c[3] for c in cells])
    rows = defaultdict(list)
    for x0, top, x1, bottom in cells:
        c0, c1, r0, r1 = _nearest(xs, x0), _nearest(xs, x1), _nearest(ys, top), _nearest(ys, bottom)
        if c1 <= c0 or r1 <= r0:
            continue
        box = (max(x0 + 1, 0), max(top + 1, 0), min(x1 - 1, page.width), min(bottom - 1, page.height))
        text = ""
        if box[2] > box[0] and box[3] > box[1]:
            text = _clean(page.crop(box).extract_text())
        rows[r0].append((c0, Cell(text, c1 - c0, r1 - r0)))
    return [[cell for _, cell in sorted(items, key=lambda t: t[0])] for _, items in sorted(rows.items())]


def _outer_tables(tables):
    """Оставляем только внешние таблицы: вложенные (внутри другой таблицы) pdfplumber находит как отдельные, это шум."""
    def inside(a, b):
        return a is not b and a.bbox[0] >= b.bbox[0] - 2 and a.bbox[1] >= b.bbox[1] - 2 \
            and a.bbox[2] <= b.bbox[2] + 2 and a.bbox[3] <= b.bbox[3] + 2
    return [t for t in tables if not any(inside(t, other) for other in tables)]


def _is_mono(chars):
    names = [c.get("fontname", "").lower() for c in chars if c["text"].strip()]
    return bool(names) and sum(any(k in n for k in MONO_FONTS) for n in names) > len(names) / 2


def _code_text(lines):
    """Строки кода с сохранением отступов (по смещению от левого края)."""
    left = min(l["x0"] for l in lines)
    widths = [(l["x1"] - l["x0"]) / max(len(l["text"].strip()), 1) for l in lines]
    char_w = median(widths) or 5
    return "\n".join(" " * int(round((l["x0"] - left) / char_w)) + l["text"].strip() for l in lines)


def _text_blocks(page, top, bottom, body_size):
    """Текст страницы между двумя высотами: заголовки, абзацы, блоки кода."""
    top, bottom = max(top, 0), min(bottom, page.height)
    if bottom - top < 3:
        return []
    region = page.crop((0, top, page.width, bottom))
    blocks, current, prev, current_heading, code = [], [], None, False, []

    def flush():
        nonlocal current, current_heading
        text = " ".join(current).strip()
        if text:
            blocks.append(Block("heading", text, level=2) if current_heading else Block("paragraph", text))
        current, current_heading = [], False

    def flush_code():
        nonlocal code
        if code:
            blocks.append(Block("code", _code_text(code)))
        code = []

    for line in region.extract_text_lines(return_chars=True):
        text = line["text"].strip()
        if not text:
            continue
        if _is_mono(line["chars"]):                 # моноширинный шрифт = код
            flush()
            code.append(line)
            prev = line
            continue
        flush_code()
        sizes = [c["size"] for c in line["chars"] if c["text"].strip()]
        size = median(sizes) if sizes else body_size
        heading = size >= body_size * 1.15 and len(text) < 160
        gap = (line["top"] - prev["bottom"]) if prev else 0
        height = max(line["bottom"] - line["top"], 1)
        # новый блок: большой интервал или смена «заголовок/текст»
        if current and (gap > height * 0.6 or heading != current_heading):
            flush()
        current.append(text)
        current_heading = heading
        prev = line
    flush()
    flush_code()
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
                    grid = _pdf_table(page, table)
                    if grid:
                        blocks.append(Block("table", grid=grid))
                    top = table.bbox[3]
                blocks += _text_blocks(page, top, page.height, body_size)
            except Exception as exc:
                raise DocumentError(f"Не удалось прочитать страницу {number} PDF.") from exc
            pages.append(Page(number, blocks))
    return ParsedDocument("PDF", name, pages)


# ---------- Word (python-docx) ----------
def _heading_level(style_name):
    name = (style_name or "").lower()
    if name in ("title", "название"):
        return 1
    for prefix in ("heading", "заголовок"):
        if name.startswith(prefix):
            digits = "".join(ch for ch in name if ch.isdigit())
            return min(int(digits), 3) if digits else 2
    return 0


def _is_code_paragraph(paragraph, style):
    if style.lower().startswith(("code", "source code", "html code", "preformatted", "код")):
        return True
    fonts = [(r.font.name or "").lower() for r in paragraph.runs if r.text.strip()]
    return bool(fonts) and all(any(k in f for k in MONO_FONTS) for f in fonts)


def _docx_table(tbl, document):
    """Таблица Word с объединёнными ячейками: gridSpan даёт colspan, vMerge даёт rowspan."""
    rows, open_cells = [], {}
    for tr in tbl.tr_lst:
        row, col = [], 0
        for tc in tr.tc_lst:
            pr = tc.find(W + "tcPr")
            span_el = pr.find(W + "gridSpan") if pr is not None else None
            span = int(span_el.get(W + "val")) if span_el is not None else 1
            vm = pr.find(W + "vMerge") if pr is not None else None
            if vm is not None and vm.get(W + "val") in (None, "continue"):    # продолжение ячейки сверху
                if col in open_cells:
                    open_cells[col].rowspan += 1
                col += span
                continue
            text = "\n".join(t for t in (Paragraph(p, document).text.strip() for p in tc.findall(W + "p")) if t)
            cell = Cell(text, span, 1)
            if vm is not None:                  # начало вертикального объединения
                open_cells[col] = cell
            else:
                open_cells.pop(col, None)
            row.append(cell)
            col += span
        if row:
            rows.append(row)
    return rows


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
        if child.tag == W + "p":
            paragraph = Paragraph(child, document)
            style = paragraph.style.name if paragraph.style is not None else ""
            if _is_code_paragraph(paragraph, style):
                text = paragraph.text.rstrip()
                if text.strip():
                    if blocks and blocks[-1].kind == "code":      # соседние строки кода — один блок
                        blocks[-1].text += "\n" + text
                    else:
                        blocks.append(Block("code", text))
                continue
            text = paragraph.text.strip()
            if not text:
                continue
            level = _heading_level(style)
            if level:
                blocks.append(Block("heading", text, level=level))
            elif style.lower().startswith(("list", "список")):
                blocks.append(Block("bullet", text))
            else:
                blocks.append(Block("paragraph", text))
        elif child.tag == W + "tbl":
            grid = _docx_table(child, document)
            if grid:
                blocks.append(Block("table", grid=grid))
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
