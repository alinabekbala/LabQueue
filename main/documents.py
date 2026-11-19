# main/documents.py
"""Чтение документов PDF и Word (ЛЗ 13).

Это «модель» нашей функции: обычный Python без привязки к вебу. Принимает файл,
возвращает структуру «страницы → блоки (заголовок, абзац, код, таблица)».
View и шаблон ничего не знают про библиотеки: pdfplumber (PDF) и python-docx (Word).
Файл читается в памяти и нигде не сохраняется.
"""
import base64
import io
import os
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from statistics import median

import pdfplumber
from docx import Document
from PIL import Image
from docx.text.paragraph import Paragraph

MAX_SIZE = 20 * 1024 * 1024         # максимальный размер загружаемого файла
MAX_PDF_PAGES = 40                  # защита от слишком больших документов
MAX_UNPACKED = 50 * 1024 * 1024     # защита от «бомбы» в .docx (это zip-архив)
MAX_IMAGES = 40                     # сколько картинок максимум показываем в одном документе
MAX_IMAGES_BYTES = 6 * 1024 * 1024  # и сколько данных они могут занять вместе
MIN_IMAGE_SIDE = 40                 # значки и линии меньше 40 пунктов картинками не считаем
Image.MAX_IMAGE_PIXELS = 40_000_000  # защита от «бомбы» в самой картинке
ALLOWED = {".pdf": "PDF", ".docx": "Word"}
MONO_FONTS = ("courier", "consolas", "mono", "menlo", "source code")
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


class DocumentError(Exception):
    """Понятная пользователю причина, почему файл не удалось прочитать."""


@dataclass
class Cell:
    text: str = ""
    colspan: int = 1                # ячейка может занимать несколько столбцов и строк
    rowspan: int = 1


@dataclass
class Block:
    kind: str                       # "heading" | "paragraph" | "bullet" | "code" | "table" | "image"
    text: str = ""
    src: str = ""                   # для картинки: data:-адрес (файл нигде не сохраняется)
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
    skipped_images: int = 0         # сколько картинок не показали из-за лимита

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
    def images_count(self):
        return sum(1 for p in self.pages for b in p.blocks if b.kind == "image")

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
    rows, taken = defaultdict(list), set()
    for x0, top, x1, bottom in cells:
        c0, c1, r0, r1 = _nearest(xs, x0), _nearest(xs, x1), _nearest(ys, top), _nearest(ys, bottom)
        if c1 <= c0 or r1 <= r0:
            continue
        box = (max(x0 + 1, 0), max(top + 1, 0), min(x1 - 1, page.width), min(bottom - 1, page.height))
        text = ""
        if box[2] > box[0] and box[3] > box[1]:
            text = _clean(page.crop(box).extract_text())
        rows[r0].append((c0, Cell(text, c1 - c0, r1 - r0)))
        for r in range(r0, r1):
            taken.update((r, c) for c in range(c0, c1))
    # достраиваем «дыры»: клетки, которых нет в PDF, превращаем в пустые, чтобы сетка была сплошной
    for r in range(len(ys) - 1):
        c = 0
        while c < len(xs) - 1:
            if (r, c) in taken:
                c += 1
                continue
            start = c
            while c < len(xs) - 1 and (r, c) not in taken:
                c += 1
            rows[r].append((start, Cell("", c - start, 1)))
    return [[cell for _, cell in sorted(items, key=lambda t: t[0])] for _, items in sorted(rows.items())]


def _is_decoration(grid):
    """Карточки и плашки слайдов (рамки с короткими подписями) pdfplumber принимает за таблицы.
    Настоящая таблица почти не имеет пустых ячеек, у «карточки» их много."""
    cells = [c for row in grid for c in row]
    empty = sum(1 for c in cells if not c.text.strip())
    return 2 <= len(grid) <= 4 and empty * 10 >= len(cells) * 3


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


def _segments(line, size):
    """Горизонтальные куски строки: пробел шире размера шрифта разделяет колонки."""
    if _is_mono(line["chars"]):
        return [(line["x0"], line["x1"])]
    chars = sorted((c for c in line["chars"] if c["text"].strip()), key=lambda c: c["x0"])
    if not chars:
        return []
    parts, start, end = [], chars[0]["x0"], chars[0]["x1"]
    for c in chars[1:]:
        if c["x0"] - end > size * 1.0:
            parts.append((start, end))
            start = c["x0"]
        end = max(end, c["x1"])
    parts.append((start, end))
    return parts


def _gutters(infos):
    """Вертикальные промежутки между колонками: они повторяются минимум в двух строках."""
    mids = []
    for _, parts in infos:
        for (_, a_end), (b_start, _) in zip(parts, parts[1:]):
            mids.append((a_end + b_start) / 2)
    groups = []
    for m in sorted(mids):
        if groups and m - groups[-1][-1] <= 12:
            groups[-1].append(m)
        else:
            groups.append([m])
    return [sum(g) / len(g) for g in groups if len(g) >= 2]


def _text_blocks(page, top, bottom, body_size):
    """Текст страницы между двумя высотами. Если на слайде текст в несколько колонок,
    каждая колонка читается отдельно (слева направо), а не строка за строкой через всю страницу."""
    top, bottom = max(top, 0), min(bottom, page.height)
    if bottom - top < 3:
        return []
    region = page.crop((0, top, page.width, bottom))
    lines = region.extract_text_lines(return_chars=True)
    infos = []
    for line in lines:
        sizes = [c["size"] for c in line["chars"] if c["text"].strip()]
        infos.append((line, _segments(line, median(sizes) if sizes else body_size)))
    gutters = _gutters(infos)
    if not gutters:
        return _region_blocks(region, body_size)
    # делим на полосы: «во всю ширину» (строка пересекает промежуток) и «колоночные»
    bands, edges = [], [0] + gutters + [page.width]
    for line, parts in infos:
        full = any(a < g < b for a, b in parts for g in gutters)
        if bands and bands[-1][0] == full:
            bands[-1][1].append(line)
        else:
            bands.append((full, [line]))
    blocks = []
    for full, band in bands:
        t, b = max(top, min(l["top"] for l in band) - 1), min(bottom, max(l["bottom"] for l in band) + 1)
        if b - t < 3:
            continue
        areas = [(0, page.width)] if full else list(zip(edges, edges[1:]))
        crops = [page.crop((x0, t, x1, b)) for x0, x1 in areas]
        if not full:
            # проверка: колонки в сумме должны содержать все символы полосы, иначе граница разрезала слова
            total = sum(1 for l in band for c in l["chars"] if c["text"].strip())
            if sum(1 for cr in crops for c in cr.chars if c["text"].strip()) != total:
                crops = [page.crop((0, t, page.width, b))]
        for crop in crops:
            blocks += _region_blocks(crop, body_size)
    return blocks


def _region_blocks(region, body_size):
    """Текст одной области (одна колонка): заголовки, абзацы, блоки кода."""
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
        if current and (gap > height * 1.2 or heading != current_heading):
            flush()
        current.append(text)
        current_heading = heading
        prev = line
    flush()
    flush_code()
    return blocks


class ImageBudget:
    """Ограничивает число и общий размер картинок, чтобы страница не раздулась."""

    def __init__(self):
        self.count = 0
        self.size = 0
        self.skipped = 0

    def block(self, image):
        """PIL-картинка -> Block("image") с data:-адресом или None, если лимит исчерпан."""
        if self.count >= MAX_IMAGES:
            self.skipped += 1
            return None
        image = image.convert("RGB")
        image.thumbnail((1400, 1400))
        buf = io.BytesIO()
        image.save(buf, "JPEG", quality=82)            # заново кодируем сами: чужие байты на страницу не попадают
        if self.size + buf.tell() > MAX_IMAGES_BYTES:
            self.skipped += 1
            return None
        self.count += 1
        self.size += buf.tell()
        src = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
        return Block("image", src=src)


def _pdf_images(page, budget):
    """Картинки страницы PDF: вырезаем по координатам. Фон на всю страницу и мелкие значки пропускаем."""
    result, seen = [], set()
    for im in sorted(page.images, key=lambda i: (round(i["top"]), i["x0"])):
        w, h = im["x1"] - im["x0"], im["bottom"] - im["top"]
        box = (max(im["x0"], 0), max(im["top"], 0), min(im["x1"], page.width), min(im["bottom"], page.height))
        key = tuple(round(v) for v in box)
        if key in seen or w < MIN_IMAGE_SIDE or h < MIN_IMAGE_SIDE:
            continue
        if w * h > 0.7 * page.width * page.height:          # картинка-фон слайда, а не иллюстрация
            continue
        seen.add(key)
        block = budget.block(page.crop(box).to_image(resolution=110).original)
        if block:
            result.append(block)
    return result


def read_pdf(file, name="document.pdf"):
    budget = ImageBudget()
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
                    grid = _pdf_table(page, table)
                    if not grid or _is_decoration(grid):    # не таблица: текст читаем как обычный
                        continue
                    blocks += _text_blocks(page, top, table.bbox[1], body_size)
                    blocks.append(Block("table", grid=grid))
                    top = table.bbox[3]
                blocks += _text_blocks(page, top, page.height, body_size)
                blocks += _pdf_images(page, budget)        # иллюстрации страницы идут после её текста
            except Exception as exc:
                raise DocumentError(f"Не удалось прочитать страницу {number} PDF.") from exc
            pages.append(Page(number, blocks))
    return ParsedDocument("PDF", name, pages, skipped_images=budget.skipped)


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


def _docx_images(paragraph_el, document, budget):
    """Картинки абзаца Word: находим связи a:blip -> файл внутри .docx, открываем через Pillow."""
    blocks = []
    for blip in paragraph_el.iter(A + "blip"):
        rid = blip.get(R + "embed")
        part = document.part.related_parts.get(rid) if rid else None
        if part is None:
            continue
        try:
            block = budget.block(Image.open(io.BytesIO(part.blob)))
        except Exception:                       # формат, который Pillow не читает (EMF, WMF), пропускаем
            continue
        if block:
            blocks.append(block)
    return blocks


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

    budget = ImageBudget()
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
            images = _docx_images(child, document, budget)
            if not text:
                blocks += images
                continue
            level = _heading_level(style)
            if level:
                blocks.append(Block("heading", text, level=level))
            elif style.lower().startswith(("list", "список")):
                blocks.append(Block("bullet", text))
            else:
                blocks.append(Block("paragraph", text))
            blocks += images
        elif child.tag == W + "tbl":
            grid = _docx_table(child, document)
            if grid:
                blocks.append(Block("table", grid=grid))
    return ParsedDocument("Word", name, [Page(None, blocks)], skipped_images=budget.skipped)


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
