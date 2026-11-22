"""Text output of `docreader parse` (contracts/cli.md «docreader parse»)."""

from docreader.clauseview import ClausePart, ClauseView, Outline, OutlineRecord
from docreader.parsing import ParsedDocument, ParseRun, SkippedDocument
from docreader.render import render_clause_text, render_outline_text, render_parse_text


def _doc(
    document_id: str = "D-0001",
    state: str = "done",
    reason: str | None = None,
    *,
    sections: int = 14,
    clauses: int = 212,
    first_page: int | None = 1,
    last_page: int | None = 38,
) -> ParsedDocument:
    return ParsedDocument(
        document_id=document_id,
        state=state,
        reason=reason,
        sections=sections,
        clauses=clauses,
        first_page=first_page,
        last_page=last_page,
        has_tail=True,
    )


def test_done_document_line() -> None:
    result = ParseRun(run_id=57, documents=[_doc()])
    assert render_parse_text(result).splitlines()[0] == (
        "D-0001  готово             разделов 14, пунктов 212, стр. 1–38"
    )


def test_needs_review_line_has_reason() -> None:
    result = ParseRun(
        run_id=57,
        documents=[
            _doc(
                "D-0002",
                "needs_review",
                "повтор: 6 (стр. 9)",
                sections=12,
                clauses=180,
                first_page=1,
                last_page=31,
            )
        ],
    )
    assert render_parse_text(result).splitlines()[0] == (
        "D-0002  требует просмотра  разделов 12, пунктов 180, стр. 1–31"
        " — повтор: 6 (стр. 9)"
    )


def test_failed_line_has_reason_and_no_counts() -> None:
    result = ParseRun(
        run_id=57,
        documents=[_doc("D-0004", "failed", "ошибка разбора", first_page=None, last_page=None)],
    )
    assert render_parse_text(result).splitlines()[0] == (
        "D-0004  ошибка             ошибка разбора"
    )


def test_missing_page_is_printed_as_dash() -> None:
    result = ParseRun(run_id=1, documents=[_doc(first_page=None, last_page=None)])
    assert render_parse_text(result).splitlines()[0].endswith("стр. —–—")


def test_skipped_line() -> None:
    result = ParseRun(
        run_id=57,
        skipped=[SkippedDocument("D-0003", "не прочитан — выполните docreader read D-0003")],
    )
    assert render_parse_text(result).splitlines()[0] == (
        "D-0003  пропущен           не прочитан — выполните docreader read D-0003"
    )


def test_totals_line_with_run_id() -> None:
    result = ParseRun(
        run_id=57,
        documents=[
            _doc("D-0001"),
            _doc("D-0002", "needs_review", "повтор: 6 (стр. 9)"),
        ],
        skipped=[SkippedDocument("D-0003", "не прочитан — выполните docreader read D-0003")],
    )
    lines = render_parse_text(result).splitlines()
    assert lines[-1] == (
        "Итого: разобрано 2, требует просмотра 1, ошибок 0, пропущено 1 (запуск 57)"
    )


def test_totals_line_without_run_id() -> None:
    result = ParseRun(run_id=None, skipped=[SkippedDocument("D-0003", "причина")])
    assert render_parse_text(result) == (
        "D-0003  пропущен           причина\n"
        "Итого: разобрано 0, требует просмотра 0, ошибок 0, пропущено 1"
    )


def test_full_output_order_and_lines() -> None:
    result = ParseRun(
        run_id=57,
        documents=[
            _doc("D-0001"),
            _doc("D-0002", "needs_review", "повтор: 6 (стр. 9)", sections=12, clauses=180,
                 first_page=1, last_page=31),
        ],
        skipped=[SkippedDocument("D-0003", "не прочитан — выполните docreader read D-0003")],
    )
    assert render_parse_text(result) == "\n".join(
        [
            "D-0001  готово             разделов 14, пунктов 212, стр. 1–38",
            "D-0002  требует просмотра  разделов 12, пунктов 180, стр. 1–31"
            " — повтор: 6 (стр. 9)",
            "D-0003  пропущен           не прочитан — выполните docreader read D-0003",
            "Итого: разобрано 2, требует просмотра 1, ошибок 0, пропущено 1 (запуск 57)",
        ]
    )


# --- `docreader outline` and `docreader clause` (feature 04, task T016) -------------------


DOC = "D-0001"


def _rec(
    key: str,
    kind: str = "clause",
    *,
    number: str | None = None,
    depth: int = 1,
    first: int = 1,
    last: int = 1,
    head: str = "",
    title: str | None = None,
    recognized: bool = False,
) -> OutlineRecord:
    return OutlineRecord(
        id=f"{DOC}/{key}",
        key=key,
        kind=kind,
        number_printed=number,
        depth=depth,
        parent=None,
        title=title,
        section_number=None,
        section_title=None,
        start=0,
        end=0,
        first_page=first,
        last_page=last,
        recognized=recognized,
        head=head,
    )


def _outline(
    records: list[OutlineRecord],
    *,
    state: str = "done",
    reason: str | None = None,
    unread: list[int] | None = None,
) -> Outline:
    return Outline(
        document_id=DOC,
        state=state,
        reason=reason,
        run_id=57,
        parsed_at="2026-11-25",
        records=records,
        unread_pages=unread or [],
    )


def _lines(outline: Outline) -> list[str]:
    return render_outline_text(outline).splitlines()


def test_outline_header_line_done() -> None:
    lines = _lines(_outline([_rec("1", number="1.", title="Предмет", head="1. Предмет")]))
    assert lines[0] == "D-0001 — разбор от 2026-11-25 (запуск 57), готово"


def test_outline_header_line_with_reason() -> None:
    outline = _outline(
        [], state="needs_review", reason="пропуск: после 5.2 идёт 5.4 (стр. 4)"
    )
    assert _lines(outline)[0] == (
        "D-0001 — разбор от 2026-11-25 (запуск 57), требует просмотра"
        " — пропуск: после 5.2 идёт 5.4 (стр. 4)"
    )


def test_outline_state_words() -> None:
    words = {"failed": "ошибка", "pending": "ожидает"}
    for state, word in words.items():
        assert _lines(_outline([], state=state))[0].endswith(f"(запуск 57), {word}")


def test_outline_indentation_follows_depth() -> None:
    lines = _lines(
        _outline(
            [
                _rec("1", "section", number="1.", depth=1, title="Предмет", head="1. Предмет"),
                _rec("1.2", number="1.2.", depth=2, head="1.2. Работы"),
                _rec("1.2.1", number="1.2.1.", depth=3, head="1.2.1. Первый"),
            ]
        )
    )
    id_width = len("D-0001/1.2.1") + 2
    rows = {line.split()[0]: line for line in lines[1:]}
    assert rows["D-0001/1"][id_width:].startswith("1. Предмет")
    assert rows["D-0001/1.2"][id_width + 2 :].startswith("1.2.")
    assert rows["D-0001/1.2.1"][id_width + 4 :].startswith("1.2.1.")


def test_outline_page_column_one_and_two_pages() -> None:
    lines = _lines(
        _outline(
            [
                _rec("1.2", number="1.2.", first=1, last=1, head="a"),
                _rec("1.2.2", number="1.2.2.", first=1, last=2, head="b"),
            ]
        )
    )
    one = lines[1].index("стр. 1")
    assert lines[1][one:].startswith("стр. 1") and "стр. 1–2" not in lines[1]
    assert lines[2].index("стр. 1–2") == one
    assert lines[2].rstrip().endswith("b")


def test_outline_recognized_mark() -> None:
    lines = _lines(
        _outline(
            [
                _rec("2.2", number="2.2.", head="x", recognized=True),
                _rec("1.1", number="1.1.", head="y"),
            ]
        )
    )
    assert lines[1].endswith(" [распознано]")
    assert "[распознано]" not in lines[2]


def test_outline_unread_page_between_records() -> None:
    lines = _lines(
        _outline(
            [
                _rec("2", "section", number="2.", first=2, last=2, title="Цена", head="2. Цена"),
                _rec("4", "section", number="4.", first=4, last=5, title="Сроки", head="4. Сроки"),
            ],
            unread=[3],
        )
    )
    assert lines[1].startswith("D-0001/2 ")
    assert lines[2].startswith("—")
    assert lines[2].split(maxsplit=1)[1] == "страница 3 не прочитана"
    assert lines[3].startswith("D-0001/4 ")


def test_outline_unread_page_before_first_record() -> None:
    lines = _lines(
        _outline([_rec("1", "section", number="1.", first=2, last=2, title="Х")], unread=[1])
    )
    assert lines[1].startswith("—") and "страница 1 не прочитана" in lines[1]
    assert lines[2].startswith("D-0001/1 ")


def test_outline_section_title_shown_once() -> None:
    lines = _lines(
        _outline(
            [
                _rec(
                    "1",
                    "section",
                    number="1.",
                    title="Предмет договора",
                    head="1. Предмет договора",
                )
            ]
        )
    )
    assert lines[1].count("Предмет договора") == 1
    assert "1. Предмет договора" in lines[1]


def test_outline_preamble_without_number() -> None:
    lines = _lines(
        _outline([_rec("преамбула", "preamble", head="Договор подряда № 7/2026", first=1)])
    )
    assert lines[1].split()[0] == "D-0001/преамбула"
    assert "Договор подряда № 7/2026" in lines[1]
    assert "стр. 1" in lines[1]


def test_outline_id_is_first_token_of_record_lines() -> None:
    lines = _lines(_outline([_rec("1.1", number="1.1.", head="x"), _rec("реквизиты", "tail")]))
    assert [line.split()[0] for line in lines[1:]] == ["D-0001/1.1", "D-0001/реквизиты"]


def _clause(
    *,
    section_title: str | None = "Предмет договора",
    first: int = 1,
    last: int = 2,
    recognized: bool = False,
) -> ClauseView:
    return ClauseView(
        id=f"{DOC}/1.2",
        section_title=section_title,
        first_page=first,
        last_page=last,
        recognized=recognized,
        records=[
            ClausePart(
                id=f"{DOC}/1.2",
                number_printed="1.2.",
                depth=2,
                start=0,
                end=0,
                text="1.2. Работы выполняются в два этапа.\n",
            ),
            ClausePart(
                id=f"{DOC}/1.2.1",
                number_printed="1.2.1.",
                depth=3,
                start=0,
                end=0,
                text="1.2.1. Первый этап.\n",
            ),
        ],
    )


def test_clause_header_with_section_title_and_pages() -> None:
    assert render_clause_text(_clause()).splitlines()[0] == (
        "D-0001/1.2 — Предмет договора, стр. 1–2"
    )


def test_clause_header_without_section_title_and_one_page() -> None:
    view = _clause(section_title=None, first=3, last=3, recognized=True)
    assert render_clause_text(view).splitlines()[0] == "D-0001/1.2, стр. 3 [распознано]"


def test_clause_parts_each_on_own_line_no_trailing_blank_lines() -> None:
    assert render_clause_text(_clause()) == (
        "D-0001/1.2 — Предмет договора, стр. 1–2\n"
        "\n"
        "1.2. Работы выполняются в два этапа.\n"
        "1.2.1. Первый этап."
    )


def test_outline_head_does_not_repeat_the_number() -> None:
    from docreader.clauseview import Outline, OutlineRecord
    from docreader.render import render_outline_text

    def rec(key: str, number: str | None, kind: str, head: str) -> OutlineRecord:
        return OutlineRecord(
            id=f"D-0001/{key}", key=key, kind=kind, number_printed=number,
            depth=key.count(".") + 1 if number else 0, parent=None, title=None,
            section_number=None, section_title=None, start=0, end=1, first_page=1,
            last_page=1, recognized=False, head=head,
        )

    outline = Outline(
        document_id="D-0001", state="done", reason=None, run_id=1, parsed_at="2026-11-22",
        records=[
            rec("1.1", "1.1.", "clause", "1.1. Подрядчик выполняет работы."),
            rec("1.2", "1.2", "clause", "1.2Оплата по счёту."),
            rec("преамбула", None, "preamble", "Договор подряда"),
        ],
        unread_pages=[],
    )
    lines = render_outline_text(outline).splitlines()
    assert lines[1].endswith("стр. 1  Подрядчик выполняет работы.")
    assert lines[2].endswith("Оплата по счёту.") and "1.2Оплата" not in lines[2]
    assert lines[3].endswith("Договор подряда")
