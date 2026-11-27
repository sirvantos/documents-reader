"""The HTML of the review page (feature 02, research R-9).

One self-contained file: the cards are embedded as JSON, the style and the script are
inline, no external address, font or `<link>`; images are relative `*.png` file names in
the same folder. Answers live in `localStorage` under the build id and leave the page as
`gold-review-<build>.json` (contracts/files.md).
"""

from __future__ import annotations

import html
import json
from typing import Any

from docreader.gold import REVIEW_FORMAT


def _embed(data: Any) -> str:
    """JSON for a `<script type="application/json">`: `<` is escaped so no text can close it."""
    return json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")


def render_html(
    build: str,
    cards: list[dict[str, Any]],
    *,
    answers_format: str = REVIEW_FORMAT,
    check: bool = False,
) -> str:
    """The page; `check=True` is the queue page of feature 06: cards with only a system
    value (one «верно» choice on a found value), answers saved as `check-review-<build>.json`."""
    meta = {"build": build, "format": answers_format, "check": check}
    return (
        _PAGE.replace("{{TITLE}}", html.escape(build))
        .replace("{{META}}", _embed(meta))
        .replace("{{CARDS}}", _embed(cards))
    )


_PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Проверка полей — {{TITLE}}</title>
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
input[type=text]{font:inherit;padding:6px 8px;border:1px solid var(--line);border-radius:6px;
background:var(--card);color:var(--ink);min-width:260px}
select{font:inherit;padding:6px;border:1px solid var(--line);border-radius:6px;
background:var(--card);color:var(--ink)}
main{max-width:1100px;margin:0 auto;padding:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;
margin:0 0 16px;scroll-margin-top:70px}
.card.cur{outline:3px solid var(--accent)}.card.done{opacity:.8}
.head{display:flex;gap:12px;align-items:baseline;flex-wrap:wrap}
.head .doc{font-weight:600}.head .mark{color:var(--muted)}
.src{margin:10px 0;padding:8px 0;border-top:1px solid var(--line)}
.src h4{margin:0 0 4px;font-size:13px;color:var(--muted);font-weight:600}
.val{font-size:18px;font-weight:600;margin:4px 0}
.quote{border-left:3px solid var(--accent);padding:4px 10px;margin:6px 0;white-space:pre-wrap}
.muted{color:var(--muted)}.err{color:var(--bad);margin:4px 0}.warn{color:var(--warn)}
.choices{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0 0;align-items:center}
.img{margin:8px 0;border:1px solid var(--line);max-width:100%;overflow:auto}
.img img{display:block;max-width:100%;height:auto}
kbd{font:12px ui-monospace,monospace;border:1px solid var(--line);border-radius:4px;padding:0 4px}
</style></head><body>
<header><b>Проверка полей</b><span id="count"></span><div class="bar"><i id="fill"></i></div>
<button id="dl">Скачать ответы</button>
<span class="muted"><kbd>1</kbd> <kbd>2</kbd> <kbd>Q</kbd> <kbd>W</kbd> значение ·
<kbd>3</kbd> другое · <kbd>4</kbd> отсутствует · <kbd>0</kbd> пропустить ·
<kbd>←</kbd> <kbd>→</kbd> карточки</span>
</header>
<main id="list"></main>
<script type="application/json" id="cards">{{CARDS}}</script>
<script type="application/json" id="meta">{{META}}</script>
<script>
const cards = JSON.parse(document.getElementById('cards').textContent);
const meta = JSON.parse(document.getElementById('meta').textContent);
const KEY = (meta.check ? 'check-review:' : 'gold-review:') + meta.build;
const MARK = {changed: 'значение изменилось после проверки', disagree: 'разошлось',
  rules_only: 'нашли только правила', none: 'никто не нашёл', model_only: 'нашла только модель',
  agree: 'совпало', needs_review: 'требует просмотра', rejected: 'отклонено'};
// keys of the choices; «3», «4» and «0» are taken, so the third and later ones are letters
const CHOICE_KEYS = ['1', '2', 'q', 'w', 'e', 'r'];
const SINGLE = ['agree', 'model_only', 'rules_only'];
let state = {};
try { state = JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) { state = {}; }
cards.forEach(c => { if (!state[c.key] && c.carried) state[c.key] = c.carried; });
let cur = 0, typing = null, typingClause = '';

function save() { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {} }
function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls;
  if (text != null) e.textContent = text; return e; }
function distinct(c) {
  const seen = new Set(); const sources = c.model ? [c.model] : [];
  sources.push(...c.rules);
  sources.forEach(s => seen.add(s.normalized));
  return seen.size;
}
// the choices of a card: [answer object, label]
function options(c) {
  const out = [];
  if (meta.check) {
    if (c.system && c.system.result === 'found') out.push([{answer: 'agree'}, 'верно']);
    return out;
  }
  const one = SINGLE.includes(c.mark) || (c.mark === 'changed' && distinct(c) === 1);
  if (one) { out.push([{answer: 'agree'}, 'верно']); return out; }
  if (c.model) out.push([{answer: 'chosen', choice: 'model'}, 'модель: ' + c.model.value]);
  c.rules.forEach((r, i) =>
    out.push([{answer: 'chosen', choice: 'rules:' + (i + 1)}, 'правила: ' + r.value]));
  return out;
}
function describe(a) {
  if (!a) return '';
  if (a.answer === 'agree') return 'верно';
  if (a.answer === 'chosen') return 'выбрано: ' + a.choice;
  if (a.answer === 'typed') return 'вписано: ' + a.value;
  if (a.answer === 'absent') return 'отсутствует';
  return 'пропущено';
}
const DATE_FORMS = [/^\\d{1,2}\\.\\d{1,2}\\.\\d{4}$/, /^\\d{4}-\\d{2}-\\d{2}$/,
  /^[«"]?\\d{1,2}[»"]?\\s+[а-яё]+\\s+\\d{4}(\\s*г\\.?)?$/i];
function checkTyped(c, text) {
  const t = text.trim();
  if (!t) return 'значение не введено';
  if (c.kind === 'amount' && !/^\\d[\\d\\s\\u00a0.,]*(?:руб\\S*|₽)?\\s*$/i.test(t))
    return 'сумма — цифры, например 1 200 000,00';
  if (c.kind === 'date' && !DATE_FORMS.some(re => re.test(t)))
    return 'дата — например 31.12.2026 или «31» декабря 2026 г.';
  return '';
}
function answer(n, a) {
  state[cards[n].key] = a; typing = null; save(); draw();
  if (n + 1 < cards.length) go(n + 1);
}
function go(n) {
  cur = Math.max(0, Math.min(cards.length - 1, n)); typing = null; draw();
  const e = document.getElementById('c' + cur); if (e) e.scrollIntoView({block: 'start'});
}
function sourceBlock(title, s) {
  const box = el('div', 'src'); box.append(el('h4', '', title));
  box.append(el('div', 'val', s.value));
  box.append(el('div', 'quote', s.quote));
  box.append(el('div', 'muted',
    'пункт ' + (s.clause || '—') + ', стр. ' + s.pages.join(', ')));
  (s.images || [s.image]).forEach(name => {
    const wrap = el('div', 'img'); const img = document.createElement('img');
    img.setAttribute('src', name); img.setAttribute('loading', 'lazy'); wrap.append(img);
    box.append(wrap);
  });
  return box;
}
function draw() {
  const list = document.getElementById('list'); list.textContent = '';
  let left = 0;
  cards.forEach((c, n) => {
    const a = state[c.key];
    if (!a) left++;
    const card = el('section', 'card'); card.id = 'c' + n;
    if (n === cur) card.classList.add('cur');
    if (a) card.classList.add('done');
    const head = el('div', 'head');
    head.append(el('span', 'doc', c.document_id), el('span', '', c.label),
      el('span', 'mark', MARK[c.mark] || c.mark),
      el('span', 'muted', (n + 1) + ' / ' + cards.length));
    card.append(head);
    if (meta.check && c.reasons && c.reasons.length)
      card.append(el('div', 'warn', 'причины: ' + c.reasons.join(', ')));
    if (meta.check && c.flags && c.flags.includes('system_changed'))
      card.append(el('div', 'warn', 'значение системы изменилось после решения'));
    if (c.model) card.append(sourceBlock(
      meta.check && c.system.unconfirmed ? 'Предложение модели — цитата не подтверждена' :
      meta.check ? 'Значение системы' : 'Модель', c.model));
    c.rules.forEach((r, i) =>
      card.append(sourceBlock(c.rules.length > 1 ? 'Правила ' + (i + 1) : 'Правила', r)));
    if (!meta.check && c.system && c.system.result === 'rejected') {
      const box = el('div', 'src');
      box.append(el('div', 'warn', 'Модель предложила значение, но проверка его отклонила: ' +
        (c.system.reason || '—')));
      if (c.system.proposed_value) box.append(el('div', 'muted',
        'предложено: ' + c.system.proposed_value));
      card.append(box);
    }
    if (!c.model && !c.rules.length)
      card.append(el('div', 'muted', 'Значения нет ни у модели, ни у правил.'));
    if (c.places.length) {
      const box = el('div', 'src'); box.append(el('h4', '', 'Где искать (поиск по словам)'));
      c.places.forEach(p => {
        box.append(el('div', 'muted', 'пункт ' + p.clause_id + ', стр. ' + p.pages.join(', ')));
        const wrap = el('div', 'img'); const img = document.createElement('img');
        img.setAttribute('src', p.image); img.setAttribute('loading', 'lazy'); wrap.append(img);
        box.append(wrap);
      });
      card.append(box);
    }
    const ch = el('div', 'choices');
    options(c).forEach(([ans, label], k) => {
      const on = a && a.answer === ans.answer && a.choice === ans.choice;
      const b = el('button', on ? 'on' : '', (CHOICE_KEYS[k] || '?').toUpperCase() + ' · ' + label);
      b.onclick = () => answer(n, ans); ch.append(b);
    });
    const other = el('button', a && a.answer === 'typed' ? 'on' : '', '3 · другое значение');
    other.onclick = () => { cur = n; typing = n; typingClause = ''; draw(); };
    const absent = el('button', a && a.answer === 'absent' ? 'on' : '', '4 · отсутствует');
    absent.onclick = () => answer(n, {answer: 'absent'});
    const skip = el('button', a && a.answer === 'skip' ? 'on' : '', '0 · пропустить');
    skip.onclick = () => answer(n, {answer: 'skip'});
    ch.append(other, absent, skip);
    card.append(ch);
    if (typing === n) {
      const row = el('div', 'choices');
      const input = document.createElement('input'); input.type = 'text'; input.id = 'typed';
      input.placeholder = 'значение, как в договоре';
      if (a && a.answer === 'typed') input.value = a.value;
      const sel = document.createElement('select');
      sel.append(new Option('пункт не указан', ''));
      c.places.forEach(p => sel.append(new Option(p.clause_id, p.clause_id)));
      sel.value = typingClause; sel.onchange = () => { typingClause = sel.value; };
      const ok = el('button', '', 'Сохранить'); const msg = el('span', 'err');
      const commit = () => {
        const bad = checkTyped(c, input.value);
        if (bad) { msg.textContent = bad; return; }
        const r = {answer: 'typed', value: input.value.trim()};
        if (typingClause) r.clause = typingClause;
        answer(n, r);
      };
      ok.onclick = commit;
      input.onkeydown = ev => {
        if (ev.key === 'Enter') { ev.preventDefault(); commit(); }
        if (ev.key === 'Escape') { typing = null; draw(); }
        ev.stopPropagation();
      };
      row.append(input, sel, ok, msg); card.append(row);
      setTimeout(() => input.focus(), 0);
    }
    if (a) card.append(el('div', 'muted', 'ответ: ' + describe(a)));
    list.append(card);
  });
  document.getElementById('count').textContent = 'осталось ' + left + ' из ' + cards.length;
  document.getElementById('fill').style.width =
    (cards.length ? 100 * (cards.length - left) / cards.length : 100) + '%';
}
// a letter by its physical key, so it works in the Russian layout too
function choiceKey(ev) {
  return ev.code && ev.code.startsWith('Key') ? ev.code.slice(3).toLowerCase() : ev.key;
}
document.addEventListener('keydown', ev => {
  if (typing !== null || ev.ctrlKey || ev.metaKey || ev.altKey || !cards.length) return;
  const c = cards[cur];
  if (ev.key === 'ArrowRight' || ev.key === 'ArrowDown') { ev.preventDefault(); go(cur + 1); }
  else if (ev.key === 'ArrowLeft' || ev.key === 'ArrowUp') { ev.preventDefault(); go(cur - 1); }
  else if (CHOICE_KEYS.indexOf(choiceKey(ev)) >= 0) {
    const o = options(c)[CHOICE_KEYS.indexOf(choiceKey(ev))]; if (o) answer(cur, o[0]);
  }
  else if (ev.key === '3') { ev.preventDefault(); typing = cur; typingClause = ''; draw(); }
  else if (ev.key === '4') answer(cur, {answer: 'absent'});
  else if (ev.key === '0') answer(cur, {answer: 'skip'});
});
document.getElementById('dl').onclick = () => {
  const out = cards.filter(c => state[c.key]).map(c => Object.assign({key: c.key}, state[c.key]));
  const blob = new Blob([JSON.stringify({format: meta.format, build: meta.build, cards: out},
    null, 1)], {type: 'application/json'});
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
  a.download = (meta.check ? 'check-review-' : 'gold-review-') + meta.build + '.json';
  document.body.append(a); a.click();
  a.remove();
};
draw();
</script></body></html>
"""
