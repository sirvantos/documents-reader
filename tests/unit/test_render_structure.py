"""Text output of `docreader parse` (contracts/cli.md «docreader parse»)."""

from docreader.parsing import ParsedDocument, ParseRun, SkippedDocument
from docreader.render import render_parse_text


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
