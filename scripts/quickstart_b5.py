"""Quickstart Б5 of feature 13 in one run: recognise and read the whole set, print numbers.

Run once on the analyst's Mac, from the repository root:

    uv run python scripts/quickstart_b5.py            # uses .env
    uv run python scripts/quickstart_b5.py --env-file .env

What it does (quickstart Б5, SC-001, SC-006, SC-008, SC-009):
  1. checks the engine settings and that Tesseract has the `rus` and `osd` data;
  2. `docreader migrate`;
  3. `docreader recognize` over the whole set, under `caffeinate -i` on macOS
     (interrupted: run the script again, recognition resumes where it stopped);
  4. `docreader read --all`, timed (SC-008: ≤ 10 min);
  5. a second `docreader recognize`, which must recognise nothing and change no state;
  6. `recognize-report`, `recognize-report --review` and `read-report` as JSON.

Only numbers are printed and saved (to `$DOCREADER_DATA_DIR/reports/b5-summary-….txt`):
no contract text, no file names, no requisites. Document ids (D-0001…) appear only in
the list of documents with the most flagged pages. This summary may be sent to the agent.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import statistics
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

FORBID = "DOCREADER_FORBID_MODELS"
PRECHECK = """
import json, tesserocr
from docreader.config import load_settings
s = load_settings()
r = s.recognition
path, langs = tesserocr.get_languages(r.model_dir) if r.model_dir else tesserocr.get_languages()
print(json.dumps({"engine": r.engine, "dpi": r.dpi, "try_rotations": r.try_rotations,
                  "langs": sorted(langs), "reports_dir": str(s.data_dir / "reports")}))
"""


class Stop(Exception):
    """A precondition or a command failed; the message says what to do."""


def uv(env_file: str, *args: str, prefix: Sequence[str] = ()) -> subprocess.CompletedProcess:
    command = [*prefix, "uv", "run", "--group", "ocr", "--env-file", env_file, *args]
    return subprocess.run(command, capture_output=True, text=True, check=False)


def docreader(env_file: str, *args: str, prefix: Sequence[str] = ()) -> tuple[float, str]:
    """Run a docreader command; return its wall time and stdout, or Stop with stderr."""
    started = time.monotonic()
    result = uv(env_file, "docreader", *args, prefix=prefix)
    seconds = time.monotonic() - started
    if result.returncode != 0:
        raise Stop(f"docreader {' '.join(args)}: код {result.returncode}\n{result.stderr.strip()}")
    return seconds, result.stdout


def as_json(text: str) -> dict | None:
    text = text.strip()
    return json.loads(text) if text.startswith("{") else None


def peak_memory_mb() -> float:
    peak = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    return peak / (1024 * 1024) if sys.platform == "darwin" else peak / 1024  # bytes vs KB


# --- the summary: numbers only (tested in tests/unit/test_quickstart_b5.py) ---------------


def _pct(part: float, whole: float) -> str:
    return f"{100 * part / whole:.1f}%" if whole else "—"


def _hms(seconds: float) -> str:
    seconds = round(seconds)
    return f"{seconds // 3600} ч {seconds % 3600 // 60:02d} мин"


def _count(flags: dict, code: str) -> int:
    value = flags.get(code, 0)
    return len(value) if isinstance(value, list) else int(value)


def _flagged(doc: dict) -> int:
    return sum(len(v) if isinstance(v, list) else int(v) for v in doc.get("flags", {}).values())


def summarize(
    *,
    machine: dict,
    precheck: dict,
    run_pages: list[dict],
    recognize_wall: float,
    report: dict,
    review: dict,
    read_report: dict,
    read_all_seconds: float,
    second_run: dict,
    states_unchanged: bool,
    peak_mb: float,
) -> list[str]:
    """The lines of the summary. Only counts, shares, times and document ids."""
    totals = report.get("totals", {})
    documents = report.get("documents", [])
    scan_pages = totals.get("scan_pages", sum(d.get("scan_pages", 0) for d in documents))
    recognized = totals.get("recognized", sum(d.get("recognized", 0) for d in documents))
    errors = totals.get("errors", sum(d.get("errors", 0) for d in documents))
    stored_seconds = totals.get("seconds", sum(d.get("seconds", 0) for d in documents))
    flags = totals.get("flags", {})
    low = _count(flags, "low_recognition_quality")
    qualities = [d["mean_quality"] for d in documents if d.get("mean_quality") is not None]

    per_page = [p["seconds"] for p in run_pages if p.get("seconds") is not None]
    turns = Counter(p.get("turn", 0) for p in run_pages if p.get("error") is None)
    review_codes = Counter(p.get("code") for p in review.get("pages", []))

    read_docs = read_report.get("documents", [])
    available = [
        d for d in read_docs if d.get("state") in ("done", "needs_review") and d.get("read", 0) > 0
    ]
    read_totals = read_report.get("totals", {})
    worst = sorted((d for d in documents if _flagged(d)), key=_flagged, reverse=True)[:10]

    lines = [
        "Quickstart Б5, фича 13 — только цифры",
        f"Дата: {datetime.now().isoformat(timespec='minutes')}",
        f"Машина: {machine['system']} {machine['release']} {machine['arch']}, "
        f"ядер {machine['cpus']}",
        f"Настройки: engine={precheck['engine']}, dpi={precheck['dpi']}, "
        f"try_rotations={precheck['try_rotations']}, языки: {', '.join(precheck['langs'])}",
        "",
        "SC-001 — каждая страница-скан распознана или с причиной",
        f"  страниц-сканов {scan_pages}, распознано {recognized}, ошибок {errors}, "
        f"без учёта {scan_pages - recognized - errors}",
        f"  флаги: низкое качество {low}, текст не найден {_count(flags, 'scan_no_text')}, "
        f"пустых {_count(flags, 'empty')}",
        f"  на просмотр: {dict(review_codes) or 'нет'}",
        f"  доля «низкое качество»: {_pct(low, recognized)}",
        "",
        "SC-006 — время распознавания (≤ 12 ч, ~25 с/стр.)",
        (
            f"  сумма по страницам (все запуски): {_hms(stored_seconds)}, "
            f"в среднем {stored_seconds / recognized:.1f} с/стр."
            if recognized
            else "  сумма по страницам: —"
        ),
        f"  этот запуск: {len(run_pages)} стр. за {_hms(recognize_wall)}",
    ]
    if per_page:
        p95 = sorted(per_page)[max(0, int(len(per_page) * 0.95) - 1)]
        lines.append(
            f"  с/стр. в этом запуске: медиана {statistics.median(per_page):.1f}, "
            f"95% ≤ {p95:.1f}, макс. {max(per_page):.1f}"
        )
    quality_line = (
        f"мин. {min(qualities):.2f}, медиана {statistics.median(qualities):.2f}, "
        f"макс. {max(qualities):.2f}"
        if qualities
        else "—"
    )
    lines += [
        f"  пик памяти дочерних процессов: {peak_mb:.0f} МБ",
        f"  доворот в этом запуске: {dict(sorted(turns.items())) or 'нет данных'}",
        f"  средняя оценка по документам: {quality_line}",
        "",
        "SC-008 — повторный запуск и перечитывание",
        f"  read --all: {read_all_seconds:.0f} с = {read_all_seconds / 60:.1f} мин (≤ 10 мин)",
        f"  второй recognize: распознано {second_run.get('pages', '?')} стр., "
        f"состояния этапов {'не изменились' if states_unchanged else 'ИЗМЕНИЛИСЬ'}",
        "",
        "SC-009 — договоры, доступные следующим этапам (≥ 95%)",
        f"  {len(available)} из {len(read_docs)} ({_pct(len(available), len(read_docs))})",
        f"  чтение: страниц {read_totals.get('pages', '?')}, прочитано "
        f"{read_totals.get('read', '?')}, таблиц {read_totals.get('tables', '?')}, "
        f"флаги {read_totals.get('flags', {})}",
        "",
        "Документы с наибольшим числом флагов (id: страниц-сканов, флагов, оценка)",
    ]
    if not worst:
        lines.append("  нет")
    for doc in worst:
        quality = doc.get("mean_quality")
        shown = f"{quality:.2f}" if quality is not None else "—"
        lines.append(f"  {doc.get('id')}: {doc.get('scan_pages', 0)}, {_flagged(doc)}, {shown}")
    return lines


# --- the run ---------------------------------------------------------------------------------


def precheck(env_file: str) -> dict:
    if not Path(env_file).is_file():
        raise Stop(f"Нет файла {env_file} — нужен DOCREADER_DATA_DIR рабочего набора")
    env_text = Path(env_file).read_text(encoding="utf-8")
    if os.environ.get(FORBID) or any(
        line.strip().startswith(f"{FORBID}=") for line in env_text.splitlines()
    ):
        raise Stop(f"{FORBID} задан — на Mac уберите его из окружения и из {env_file}")
    sync = subprocess.run(
        ["uv", "sync", "--group", "ocr"], capture_output=True, text=True, check=False
    )
    if sync.returncode != 0:
        raise Stop(f"uv sync --group ocr: {sync.stderr.strip()}")
    result = uv(env_file, "python", "-c", PRECHECK)
    if result.returncode != 0:
        raise Stop(f"Проверка движка не прошла:\n{result.stderr.strip()}")
    found: dict = json.loads(result.stdout.strip().splitlines()[-1])
    if found["engine"] != "tesseract":
        raise Stop(f"[recognition] engine = {found['engine']!r}, нужен tesseract")
    missing = {"rus", "osd"} - set(found["langs"])
    if missing:
        raise Stop(
            f"У Tesseract нет данных {', '.join(sorted(missing))} — brew install tesseract "
            "tesseract-lang (или [recognition] model_dir)"
        )
    return found


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Quickstart Б5 фичи 13: прогон набора, цифры.")
    parser.add_argument("--env-file", default=".env", help="файл с DOCREADER_DATA_DIR (.env)")
    env_file = parser.parse_args(argv).env_file
    try:
        print("1/6 проверка движка…", flush=True)
        found = precheck(env_file)
        print("2/6 migrate…", flush=True)
        docreader(env_file, "migrate")
        print("3/6 распознавание набора (долго; прервали — запустите скрипт ещё раз)…", flush=True)
        keep_awake = ["caffeinate", "-i"] if sys.platform == "darwin" else []
        wall, out = docreader(
            env_file, "recognize", "--label", "quickstart Б5", "--json", prefix=keep_awake
        )
        first = as_json(out) or {}
        run_pages = [p for d in first.get("documents", []) for p in d.get("pages", [])]
        print("4/6 read --all…", flush=True)
        read_all, _ = docreader(env_file, "read", "--all")
        _, before = docreader(env_file, "read-report", "--json")
        print("5/6 повторный recognize…", flush=True)
        _, again = docreader(env_file, "recognize", "--json")
        second_totals = (as_json(again) or {}).get("totals", {"pages": 0})
        _, after = docreader(env_file, "read-report", "--json")
        states = [
            {d["id"]: d.get("state") for d in json.loads(text)["documents"]}
            for text in (before, after)
        ]
        print("6/6 отчёты…", flush=True)
        _, report = docreader(env_file, "recognize-report", "--json")
        _, review = docreader(env_file, "recognize-report", "--review", "--json")
        lines = summarize(
            machine={
                "system": platform.system(),
                "release": platform.mac_ver()[0] or platform.release(),
                "arch": platform.machine(),
                "cpus": os.cpu_count(),
            },
            precheck=found,
            run_pages=run_pages,
            recognize_wall=wall,
            report=as_json(report) or {},
            review=as_json(review) or {},
            read_report=json.loads(after),
            read_all_seconds=read_all,
            second_run=second_totals,
            states_unchanged=states[0] == states[1],
            peak_mb=peak_memory_mb(),
        )
    except Stop as exc:
        print(f"\nОстановлено: {exc}", file=sys.stderr)
        return 1
    text = "\n".join(lines) + "\n"
    reports = Path(found["reports_dir"])
    reports.mkdir(parents=True, exist_ok=True)
    target = reports / f"b5-summary-{datetime.now():%Y%m%d-%H%M%S}.txt"
    target.write_text(text, encoding="utf-8")
    print("\n" + text + f"\nСохранено: {target}\nЭтот текст можно отправить агенту.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
