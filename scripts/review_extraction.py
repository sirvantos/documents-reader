"""Quickstart Б5 of feature 05: a local page for the manual check of extracted fields.

Run from the repository root on the analyst's Mac, after `extract --all`:

    uv run --env-file .env python scripts/review_extraction.py
    uv run --env-file .env python scripts/review_extraction.py --ids D-0054,D-0001
    uv run --env-file .env python scripts/review_extraction.py \
        --summary ~/Downloads/review-05-answers.json

Without `--summary` it builds `$DOCREADER_DATA_DIR/reports/review-05-<time>/index.html`: one
card per field of the Б5 contracts (the pick of `quickstart_extraction.py`, or `--ids`) with
the value, the quote, the page image with the quote lines marked, a link to the PDF at
that page and hints (never verdicts). The analyst marks each card with a key; the page
keeps the answers in the browser and downloads them as `review-05-answers.json`: card
keys and chosen answers only.

With `--summary` it prints the counts of SC-002 and SC-003 from that file and saves them
to `reports/extraction-b5-summary-<time>.txt`. Only that summary may be sent to the agent:
counts, document ids, field labels and error kinds. The page itself holds contract text
and never leaves the Mac (Constitution I).
"""

# No `from __future__ import annotations`: the tests load this file without registering it in
# sys.modules, and `@dataclass` then cannot resolve string annotations.

import argparse
import html
import importlib.util
import json
import os
import re
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import psycopg
from PIL import Image, ImageDraw

from docreader.config import load_settings
from docreader.db import connect
from docreader.fields import FIELD_NAMES, PROTOTYPE_FIELDS
from docreader.fieldview import load_fields
from docreader.ids import parse_document_id
from docreader.ocr import display_point

DPI = 110
VAT_RATES = (Decimal("1.20"), Decimal("1.22"))
VAT_TOLERANCE = Decimal("1.00")
MAJORITY_SHARE = 0.5
PARTY_FIELDS = ("customer_name_short", "contractor_name_short")
_LABEL = {f.name: f.label for f in PROTOTYPE_FIELDS}
_DOC_ID = re.compile(r"^D-\d{4,}$")

# The answers a card offers, by the extraction result (quickstart Б5).
CHOICES: dict[str, tuple[tuple[str, str], ...]] = {
    "found": (("correct", "верно"), ("wrong", "неверно"), ("invented", "придумано")),
    "not_found": (("correct_absent", "верно «не найдено»"), ("missed", "пропуск")),
    "rejected": (("right_reject", "верное отклонение"), ("wrong_reject", "неверное отклонение")),
    "failed": (("correct_absent", "верно «не найдено»"), ("missed", "пропуск")),
}
# Columns of the summary, in this order.
ANSWERS: tuple[tuple[str, str], ...] = (
    ("correct", "верно"),
    ("correct_absent", "верно «не найдено»"),
    ("wrong", "неверно"),
    ("missed", "пропуск"),
    ("invented", "придумано"),
    ("right_reject", "верное отклонение"),
    ("wrong_reject", "неверное отклонение"),
)
NEEDS_KIND = {"wrong", "invented", "missed", "wrong_reject"}
ERROR_KINDS: tuple[tuple[str, str], ...] = (
    ("other_value", "в договоре другое значение"),
    ("other_clause", "взято из другого пункта"),
    ("other_party", "не та сторона"),
    ("other_date", "дата другого события"),
    ("recognition", "ошибка распознавания"),
    ("format", "перенос или формат в тексте"),
    ("other", "другое"),
)
_ANSWER_LABEL = dict(ANSWERS)
_KIND_LABEL = dict(ERROR_KINDS)
_CORRECT = {"correct", "correct_absent"}


# --- pure parts --------------------------------------------------------------------------


def pixel_box(
    box: Sequence[float], *, crop: Sequence[float], rotation: int, scale: float
) -> tuple[float, float, float, float]:
    """`(left, bottom, right, top)` in unrotated PDF space → `(x0, y0, x1, y1)` image pixels.

    The image is the page rendered in display orientation (as PDFium renders it), top-left
    origin; the inverse of `ocr.image_box_to_pdf` without the recognition turn.
    """
    width, height = crop[2] - crop[0], crop[3] - crop[1]
    disp_h = width if rotation in (90, 270) else height
    xs, ys = [], []
    for x in (box[0], box[2]):
        for y in (box[1], box[3]):
            dx, dy = display_point(x - crop[0], y - crop[1], rotation, width, height)
            xs.append(dx * scale)
            ys.append((disp_h - dy) * scale)
    return (min(xs), min(ys), max(xs), max(ys))


def _amount(value: str | None) -> Decimal | None:
    if not value:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def vat_hint(without_vat: str | None, with_vat: str | None) -> str | None:
    """A hint when the price with VAT is not the price without VAT at 20% or 22%."""
    a, b = _amount(without_vat), _amount(with_vat)
    if a is None or b is None:
        return None
    if any(abs(a * rate - b) <= VAT_TOLERANCE for rate in VAT_RATES):
        return None
    return "цена с НДС не равна цене без НДС × 1,20 или × 1,22 — проверьте обе суммы"


def party_hints(
    values: dict[str, str | None], majority: dict[str, tuple[str, float]]
) -> list[str]:
    """Hints on the parties: the same name twice, a name unlike most of the set."""
    hints = []
    customer, contractor = (values.get(f) for f in PARTY_FIELDS)
    if customer and contractor and customer == contractor:
        hints.append("заказчик и подрядчик совпадают")
    for name in PARTY_FIELDS:
        value = values.get(name)
        usual = majority.get(name)
        if value and usual and usual[1] > MAJORITY_SHARE and value != usual[0]:
            hints.append(
                f"{_LABEL[name]} отличается от большинства договоров набора "
                f"({round(usual[1] * 100)}%)"
            )
    return hints


def summarize(answers: dict[str, Any]) -> list[str]:
    """Counts of SC-002 and SC-003 from the downloaded answers: no text of the contracts.

    Every printed string comes from this file (labels, kinds) or matches a document id;
    a record with anything else is dropped and counted.
    """
    items, dropped = [], 0
    for raw in answers.get("items", []):
        doc, name, result, answer = (
            raw.get("document_id"), raw.get("field"), raw.get("result"), raw.get("answer")
        )
        ok = (
            isinstance(doc, str) and bool(_DOC_ID.match(doc)) and name in FIELD_NAMES
            and result in CHOICES
            and (answer is None or answer in {c for c, _ in CHOICES[result]})
        )
        if not ok:
            dropped += 1
            continue
        kind = raw.get("error_kind")
        items.append((doc, name, answer, kind if kind in _KIND_LABEL else None))

    marked = [i for i in items if i[2] is not None]
    docs = sorted({i[0] for i in items})
    lines = [
        "Б5. Ручная проверка извлечения (SC-002, SC-003)",
        f"  договоров: {len(docs)}, полей: {len(items)}, отмечено: {len(marked)}",
    ]
    if len(marked) < len(items):
        lines.append(f"  не отмечено: {len(items) - len(marked)}")
    if dropped:
        lines.append(f"  отброшено записей: {dropped}")
    lines.append("  по полям (" + " / ".join(label for _, label in ANSWERS) + "):")
    for name in FIELD_NAMES:
        counts = Counter(i[2] for i in marked if i[1] == name)
        lines.append(f"    {_LABEL[name]}: " + " / ".join(str(counts[a]) for a, _ in ANSWERS))

    total = len(items)
    correct = sum(1 for i in marked if i[2] in _CORRECT)
    invented = sum(1 for i in marked if i[2] == "invented")
    need = -(-total * 9 // 10)  # 90%, rounded up
    if total and len(marked) == total:
        verdict = "выполнен" if correct >= need else "не выполнен"
        lines.append(
            f"  SC-002: верных результатов {correct} из {total} ({round(correct * 100 / total)}%)"
            f" — порог {need} (90%): {verdict}"
        )
        sc3 = "выполнен" if invented == 0 else "не выполнен"
        lines.append(f"  SC-003: придуманных значений {invented} — {sc3}")
    else:
        lines.append(f"  SC-002: не посчитан — отмечено {len(marked)} из {total}")
        lines.append(f"  SC-003: придуманных значений пока {invented} — не посчитан")

    errors = [i for i in marked if i[2] in NEEDS_KIND]
    if errors:
        lines.append("  ошибки (договор, поле, вид):")
        for doc, name, answer, kind in sorted(errors):
            what = _KIND_LABEL[kind] if kind else "вид не указан"
            lines.append(f"    {doc}, {_LABEL[name]}: {what} ({_ANSWER_LABEL[answer]})")
    return lines


# --- the cards from the database ---------------------------------------------------------


@dataclass
class Built:
    cards: int
    images: int
    path: Path


def _majority(conn: psycopg.Connection) -> dict[str, tuple[str, float]]:
    result = {}
    for name in PARTY_FIELDS:
        values = [
            r[0]
            for r in conn.execute(
                "SELECT value_normalized FROM field_value WHERE field = %s AND result = 'found'",
                (name,),
            )
        ]
        if values:
            value, n = Counter(values).most_common(1)[0]
            result[name] = (value, n / len(values))
    return result


def _quote_lines(
    conn: psycopg.Connection, doc_id: str, start: int, end: int
) -> dict[int, list[int]]:
    lines: dict[int, list[int]] = {}
    for page, index in conn.execute(
        "SELECT page_number, line_index FROM text_span"
        " WHERE document_id = %s AND start < %s AND end_ > %s ORDER BY start",
        (doc_id, end, start),
    ):
        lines.setdefault(page, []).append(index)
    return lines


def _line_boxes(
    conn: psycopg.Connection, doc_id: str, page: int, indexes: Sequence[int]
) -> tuple[int, list[list[float]]]:
    row = conn.execute(
        "SELECT rotation, lines FROM page_text WHERE document_id = %s AND page_number = %s",
        (doc_id, page),
    ).fetchone()
    if row is None:
        return 0, []
    rotation, lines = row
    wanted = set(indexes)
    return rotation, [ln["bbox"] for ln in lines if ln.get("i") in wanted]


def _clause_page(conn: psycopg.Connection, doc_id: str, key: str | None) -> int | None:
    if not key:
        return None
    row = conn.execute(
        "SELECT first_page FROM clause WHERE document_id = %s AND key = %s", (doc_id, key)
    ).fetchone()
    return row[0] if row else None


def _render(
    pdf: Any, page: int, rotation: int, boxes: list[list[float]], path: Path
) -> dict[str, Any]:
    pdf_page = pdf[page - 1]
    crop = pdf_page.get_cropbox()
    scale = DPI / 72
    image = pdf_page.render(scale=scale).to_pil().convert("RGB")
    w, h = image.size
    pixels = []
    for box in boxes:
        x0, y0, x1, y1 = pixel_box(box, crop=crop, rotation=rotation, scale=scale)
        x0, y0 = max(0.0, x0 - 3), max(0.0, y0 - 3)
        x1, y1 = min(float(w), x1 + 3), min(float(h), y1 + 3)
        if x1 > x0 and y1 > y0:
            pixels.append([round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)])
    overlay = image.copy()
    draw = ImageDraw.Draw(overlay)
    for x0, y0, x1, y1 in pixels:
        draw.rectangle((x0, y0, x1, y1), fill=(255, 220, 0))
    marked = Image.blend(image, overlay, 0.35)
    draw = ImageDraw.Draw(marked)
    for x0, y0, x1, y1 in pixels:
        draw.rectangle((x0, y0, x1, y1), outline=(220, 0, 0), width=2)
    path.parent.mkdir(parents=True, exist_ok=True)
    marked.save(path, "PNG", optimize=True)
    return {"file": "", "page": page, "width": w, "height": h, "boxes": pixels}


def build_review(
    conn: psycopg.Connection, originals: Path, doc_ids: Sequence[str], out: Path
) -> Built:
    """Write `out/index.html` and `out/pages/*.png` for the documents `doc_ids`."""
    from docreader.pdfpages import open_pdf

    majority = _majority(conn)
    cards: list[dict[str, Any]] = []
    images = 0
    for doc_id in doc_ids:
        view = load_fields(conn, parse_document_id(doc_id))
        sha = conn.execute("SELECT sha256 FROM document WHERE id = %s", (doc_id,)).fetchone()[0]
        pdf_path = (originals / f"{sha}.pdf").resolve()
        values = {f.field: f.value_normalized for f in view.fields if f.result == "found"}
        doc_hints = party_hints(values, majority)
        vat = vat_hint(values.get("amount_without_vat"), values.get("amount_with_vat"))
        pdf = open_pdf(pdf_path)
        try:
            for f in view.fields:
                hints = (
                    [h for h in doc_hints if "совпадают" in h or _LABEL[f.field] in h]
                    if f.field in PARTY_FIELDS
                    else []
                )
                if vat and f.field in ("amount_without_vat", "amount_with_vat"):
                    hints.append(vat)
                if f.low_quality:
                    hints.append("страница цитаты распознана с низким качеством")
                pages: dict[int, list[int]] = {}
                if f.result == "found" and f.quote_start is not None and f.quote_end is not None:
                    pages = _quote_lines(conn, doc_id, f.quote_start, f.quote_end)
                    if not pages and f.page:
                        pages = {f.page: []}
                elif f.result == "rejected":
                    first = _clause_page(conn, doc_id, f.proposed_clause)
                    if first:
                        pages = {first: []}
                card_images = []
                for page, indexes in sorted(pages.items())[:3]:
                    rotation, boxes = _line_boxes(conn, doc_id, page, indexes)
                    name = f"pages/{doc_id}-{f.field}-{page}.png"
                    info = _render(pdf, page, rotation, boxes, out / name)
                    info["file"] = name
                    card_images.append(info)
                    images += 1
                first_page = f.page or (min(pages) if pages else 1)
                cards.append({
                    "document_id": doc_id,
                    "field": f.field,
                    "label": f.label,
                    "result": f.result,
                    "value": f.value_text,
                    "quote": f.quote,
                    "clause": f.clause_id,
                    "page": first_page,
                    "reason": f.reason,
                    "proposed_value": f.proposed_value,
                    "proposed_quote": f.proposed_quote,
                    "proposed_clause": f.proposed_clause,
                    "hints": hints,
                    "choices": [list(c) for c in CHOICES[f.result]],
                    "images": card_images,
                    "pdf": f"{pdf_path.as_uri()}#page={first_page}",
                })
        finally:
            pdf.close()
    out.mkdir(parents=True, exist_ok=True)
    path = out / "index.html"
    path.write_text(render_html(cards, out.name), encoding="utf-8")
    return Built(cards=len(cards), images=images, path=path)


_CARDS_RE = re.compile(
    r'<script type="application/json" id="cards">(.*?)</script>', re.DOTALL
)


def load_cards(page: str) -> list[dict[str, Any]]:
    """The cards embedded in a page written by `build_review`."""
    match = _CARDS_RE.search(page)
    if match is None:
        raise ValueError("на странице нет данных карточек")
    return list(json.loads(match.group(1)))


def render_html(cards: list[dict[str, Any]], build_id: str) -> str:
    data = json.dumps(cards, ensure_ascii=False).replace("<", "\\u003c")
    meta = json.dumps(
        {"build": build_id, "kinds": ERROR_KINDS, "needs_kind": sorted(NEEDS_KIND)},
        ensure_ascii=False,
    ).replace("<", "\\u003c")
    return _PAGE.replace("{{TITLE}}", html.escape(build_id)).replace(
        "{{CARDS}}", data
    ).replace("{{META}}", meta)


_PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Проверка извлечения — {{TITLE}}</title>
<style>
:root{--bg:#f6f6f3;--card:#fff;--ink:#1d1d1b;--muted:#6b6b66;--line:#ddddd6;--accent:#2457c5;
--ok:#1f7a3a;--bad:#b3261e;--warn:#8a5a00}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--card:#20201e;--ink:#ecece6;
--muted:#9d9d96;--line:#3a3a36;--accent:#7fa6ff;--ok:#6fcf8a;--bad:#ff8a80;--warn:#e0b25a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.45 -apple-system,system-ui,sans-serif}
header{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);
padding:10px 16px;display:flex;gap:16px;align-items:center;flex-wrap:wrap}
header b{font-size:16px}
.bar{flex:1;min-width:160px;height:8px;background:var(--line);border-radius:4px}
.bar i{display:block;height:100%;background:var(--accent);border-radius:4px;width:0}
button{font:inherit;padding:6px 12px;border:1px solid var(--line);border-radius:6px;
background:var(--card);color:var(--ink);cursor:pointer}
button.on{background:var(--accent);border-color:var(--accent);color:#fff}
main{max-width:1100px;margin:0 auto;padding:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;
margin:0 0 16px;scroll-margin-top:70px}
.card.cur{outline:3px solid var(--accent)}.card.done{opacity:.8}
.head{display:flex;gap:12px;align-items:baseline;flex-wrap:wrap}
.head .doc{font-weight:600}.head .res{color:var(--muted)}
.val{font-size:18px;font-weight:600;margin:6px 0}.quote{border-left:3px solid var(--accent);
padding:4px 10px;margin:6px 0;color:var(--ink);white-space:pre-wrap}
.muted{color:var(--muted)}.hint{color:var(--warn);margin:4px 0}
.choices,.kinds{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0 0}
.kinds{display:none}.card.ask .kinds{display:flex}
.img{position:relative;margin:10px 0;border:1px solid var(--line);max-width:100%;overflow:auto}
.img img{display:block;max-width:100%;height:auto}
kbd{font:12px ui-monospace,monospace;border:1px solid var(--line);border-radius:4px;padding:0 4px}
</style></head><body>
<header><b>Проверка извлечения</b><span id="count"></span><div class="bar"><i id="fill"></i></div>
<button id="dl">Скачать ответы</button>
<span class="muted"><kbd>1</kbd>–<kbd>3</kbd> ответ · <kbd>a</kbd>–<kbd>g</kbd> вид ошибки ·
<kbd>j</kbd>/<kbd>k</kbd> карточки · <kbd>o</kbd> открыть PDF</span></header>
<main id="list"></main>
<script type="application/json" id="cards">{{CARDS}}</script>
<script type="application/json" id="meta">{{META}}</script>
<script>
const cards = JSON.parse(document.getElementById('cards').textContent);
const meta = JSON.parse(document.getElementById('meta').textContent);
const KEY = 'review-05:' + meta.build;
const RESULT = {found:'найдено', not_found:'не найдено', rejected:'отклонено', failed:'ошибка'};
let state = {};
try { state = JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) { state = {}; }
const id = c => c.document_id + '/' + c.field;
let cur = 0;
function save() { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {} }
function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls;
  if (text != null) e.textContent = text; return e; }
function draw() {
  const list = document.getElementById('list'); list.textContent = '';
  cards.forEach((c, n) => {
    const s = state[id(c)] || {};
    const card = el('section', 'card'); card.id = 'c' + n;
    if (n === cur) card.classList.add('cur');
    if (s.answer && (!meta.needs_kind.includes(s.answer) || s.kind)) card.classList.add('done');
    if (s.answer && meta.needs_kind.includes(s.answer)) card.classList.add('ask');
    const head = el('div', 'head');
    head.append(el('span', 'doc', c.document_id), el('span', '', c.label),
      el('span', 'res', RESULT[c.result] || c.result),
      el('span', 'muted', (n + 1) + ' / ' + cards.length));
    card.append(head);
    if (c.result === 'found') {
      card.append(el('div', 'val', c.value));
      card.append(el('div', 'quote', c.quote));
      card.append(el('div', 'muted',
        (c.clause || 'пункт не найден в разборе') + ', стр. ' + c.page));
    } else if (c.result === 'rejected') {
      card.append(el('div', 'val', 'Предложено: ' + (c.proposed_value || '—')));
      if (c.proposed_quote) card.append(el('div', 'quote', c.proposed_quote));
      card.append(el('div', 'muted', 'Причина: ' + (c.reason || '—') +
        (c.proposed_clause ? ' · пункт ' + c.proposed_clause : '')));
    } else {
      card.append(el('div', 'val', 'Не найдено'));
      card.append(el('div', 'muted', 'Найдите поле в PDF сами: есть ли значение в договоре?'));
    }
    c.hints.forEach(h => card.append(el('div', 'hint', '⚠ ' + h)));
    const ch = el('div', 'choices');
    c.choices.forEach(([code, label], k) => {
      const b = el('button', s.answer === code ? 'on' : '', (k + 1) + ' · ' + label);
      b.onclick = () => choose(n, code); ch.append(b);
    });
    const open = el('button', '', 'Открыть PDF'); open.onclick = () => window.open(c.pdf, '_blank');
    ch.append(open); card.append(ch);
    const kinds = el('div', 'kinds');
    meta.kinds.forEach(([code, label], k) => {
      const b = el('button', s.kind === code ? 'on' : '', 'abcdefg'[k] + ' · ' + label);
      b.onclick = () => kind(n, code); kinds.append(b);
    });
    card.append(kinds);
    c.images.forEach(im => {
      const box = el('div', 'img'); const img = el('img'); img.src = im.file; img.loading = 'lazy';
      img.alt = 'стр. ' + im.page; box.append(img); card.append(box);
    });
    card.onclick = () => { if (cur !== n) { cur = n; draw(); } };
    list.append(card);
  });
  const done = cards.filter(c => { const s = state[id(c)] || {};
    return s.answer && (!meta.needs_kind.includes(s.answer) || s.kind); }).length;
  document.getElementById('count').textContent = 'отмечено ' + done + ' из ' + cards.length;
  document.getElementById('fill').style.width = (100 * done / cards.length) + '%';
}
function go(n) { cur = Math.max(0, Math.min(cards.length - 1, n)); draw();
  document.getElementById('c' + cur).scrollIntoView({block: 'start'}); }
function choose(n, code) { const s = state[id(cards[n])] = state[id(cards[n])] || {};
  s.answer = code; if (!meta.needs_kind.includes(code)) delete s.kind; save();
  if (meta.needs_kind.includes(code)) { cur = n; draw(); } else go(n + 1); }
function kind(n, code) { const s = state[id(cards[n])]; if (!s) return;
  s.kind = code; save(); go(n + 1); }
document.addEventListener('keydown', e => {
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  const c = cards[cur]; const k = e.key.toLowerCase();
  if (/^[1-9]$/.test(k) && +k <= c.choices.length) choose(cur, c.choices[+k - 1][0]);
  else if ('abcdefg'.includes(k) && k.length === 1 && (state[id(c)] || {}).answer &&
           meta.needs_kind.includes(state[id(c)].answer))
    kind(cur, meta.kinds['abcdefg'.indexOf(k)][0]);
  else if (k === 'j' || e.key === 'ArrowDown') { e.preventDefault(); go(cur + 1); }
  else if (k === 'k' || e.key === 'ArrowUp') { e.preventDefault(); go(cur - 1); }
  else if (k === 'o') window.open(c.pdf, '_blank');
});
document.getElementById('dl').onclick = () => {
  const items = cards.map(c => { const s = state[id(c)] || {};
    return {document_id: c.document_id, field: c.field, result: c.result,
            answer: s.answer || null, error_kind: s.kind || null}; });
  const blob = new Blob([JSON.stringify({version: 1, build: meta.build, items}, null, 1)],
                        {type: 'application/json'});
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
  a.download = 'review-05-answers.json'; a.click();
};
const first = cards.findIndex(c => !(state[id(c)] || {}).answer);
cur = first < 0 ? 0 : first; draw();
</script></body></html>
"""


# --- command line ------------------------------------------------------------------------


def _read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _b5_pick(conn: psycopg.Connection) -> list[str]:
    path = Path(__file__).with_name("quickstart_extraction.py")
    spec = importlib.util.spec_from_file_location("quickstart_extraction", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return list(module.collect(conn).review)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--ids", help="document ids, comma-separated (default: the Б5 pick)")
    parser.add_argument("--summary", help="the downloaded review-05-answers.json")
    args = parser.parse_args(argv)
    env = _read_env(Path(args.env_file)) if Path(args.env_file).is_file() else {}
    os.environ.update({k: v for k, v in env.items() if k not in os.environ})
    if not os.environ.get("DOCREADER_DATA_DIR"):
        sys.exit(f"Нет DOCREADER_DATA_DIR (ни в окружении, ни в {args.env_file})")
    settings = load_settings()
    reports = settings.reports_dir
    reports.mkdir(parents=True, exist_ok=True)
    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"

    if args.summary:
        data = json.loads(Path(args.summary).expanduser().read_text(encoding="utf-8"))
        text = "\n".join(summarize(data)) + "\n"
        print(text, end="")
        saved = reports / f"extraction-b5-summary-{stamp}.txt"
        saved.write_text(text, encoding="utf-8")
        print(f"\nСводка сохранена: {saved} (её можно прислать агенту)")
        return 0

    with connect(settings) as conn:
        ids = [i.strip() for i in args.ids.split(",") if i.strip()] if args.ids else _b5_pick(conn)
        if not ids:
            sys.exit("Нет договоров для проверки: сначала docreader extract --all")
        built = build_review(conn, settings.originals_dir, ids, reports / f"review-05-{stamp}")
    print(f"Договоров: {len(ids)}, карточек: {built.cards}, страниц-картинок: {built.images}")
    print(f"Откройте: open {built.path}")
    print("Страница содержит текст договоров — не присылайте её; пришлите только вывод --summary.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
