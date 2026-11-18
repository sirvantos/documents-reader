from docreader.render import render_document_text, render_find_text, render_page_text, render_read_text


def _doc(seq: int, *, pages: int = 3, state: str = "done", reason: str | None = None,
         text_changed: bool = False) -> dict:
    return {
        "id": f"D-{seq:04d}",
        "pages": pages,
        "state": state,
        "reason": reason,
        "text_changed": text_changed,
        "flags": {},
    }


def _result(documents: list[dict], *, done: int = 0, needs_review: int = 0,
            failed: int = 0) -> dict:
    return {
        "run_id": 42,
        "documents": documents,
        "totals": {"done": done, "needs_review": needs_review, "failed": failed},
        "interrupted": False,
    }


def _header(text: str) -> str:
    return text.splitlines()[0]


# --- read: header and plural forms ---------------------------------------------------


def test_header_uses_plural_forms():
    cases = {
        1: "документ",
        2: "документа",
        5: "документов",
        11: "документов",
        12: "документов",
        21: "документ",
        22: "документа",
        25: "документов",
    }
    for count, word in cases.items():
        documents = [_doc(i + 1) for i in range(count)]
        text = render_read_text(_result(documents, done=count))
        assert _header(text) == f"Чтение, запуск 42: {count} {word}", count


def test_header_for_one_document_matches_contract_wording():
    text = render_read_text(_result([_doc(1, pages=24)], done=1))
    assert _header(text) == "Чтение, запуск 42: 1 документ"


# --- read: document lines ------------------------------------------------------------


def test_document_line_pads_pages_to_two_columns_as_in_contract():
    documents = [_doc(1, pages=24), _doc(3, pages=3)]
    lines = render_read_text(_result(documents, done=2)).splitlines()
    assert lines[1] == "D-0001  24 стр.  готово"
    assert lines[2] == "D-0003   3 стр.  готово"


def test_each_state_word_is_rendered():
    documents = [
        _doc(1, state="done"),
        _doc(2, state="needs_review"),
        _doc(3, state="failed"),
    ]
    text = render_read_text(_result(documents, done=1, needs_review=1, failed=1))
    lines = text.splitlines()
    assert lines[1].endswith("стр.  готово")
    assert lines[2].endswith("стр.  требует просмотра")
    assert lines[3].endswith("стр.  ошибка")


def test_reason_suffix_only_when_reason_present():
    documents = [
        _doc(2, state="needs_review", pages=12,
             reason="стр. 11: скан, не прочитана; стр. 12: возможно, не русский текст"),
        _doc(1, state="done", pages=24, reason=None),
    ]
    lines = render_read_text(_result(documents, done=1, needs_review=1)).splitlines()
    assert lines[1] == (
        "D-0002  12 стр.  требует просмотра: "
        "стр. 11: скан, не прочитана; стр. 12: возможно, не русский текст"
    )
    assert lines[2] == "D-0001  24 стр.  готово"


# --- read: text_changed line and totals ----------------------------------------------


def test_text_changed_line_lists_changed_documents():
    documents = [
        _doc(1, text_changed=True),
        _doc(2),
        _doc(4, text_changed=True),
    ]
    text = render_read_text(_result(documents, done=3))
    assert (
        "Текст изменился, следующие этапы сброшены: D-0001, D-0004" in text.splitlines()
    )


def test_text_changed_line_absent_when_nothing_changed():
    text = render_read_text(_result([_doc(1), _doc(2)], done=2))
    assert "Текст изменился" not in text


def test_totals_line_is_last():
    documents = [
        _doc(1, state="done"),
        _doc(2, state="needs_review", reason="причина"),
        _doc(3, state="failed", reason="файл копии не найден"),
    ]
    text = render_read_text(_result(documents, done=1, needs_review=1, failed=1))
    assert text.splitlines()[-1] == "Итого: готово 1, требует просмотра 1, ошибка 1"


def test_full_contract_example_layout():
    documents = [
        _doc(1, pages=24, state="done"),
        _doc(2, pages=12, state="needs_review",
             reason="стр. 11: скан, не прочитана; стр. 12: возможно, не русский текст"),
        _doc(3, pages=3, state="failed",
             reason="файл копии не найден — проверьте docreader verify D-0003"),
    ]
    result = _result(documents, done=1, needs_review=1, failed=1)
    result["documents"][0]["text_changed"] = True
    text = render_read_text(result)
    assert text.splitlines() == [
        "Чтение, запуск 42: 3 документа",
        "D-0001  24 стр.  готово",
        "D-0002  12 стр.  требует просмотра: стр. 11: скан, не прочитана; "
        "стр. 12: возможно, не русский текст",
        "D-0003   3 стр.  ошибка: файл копии не найден — проверьте docreader verify D-0003",
        "Текст изменился, следующие этапы сброшены: D-0001",
        "Итого: готово 1, требует просмотра 1, ошибка 1",
    ]


# --- text: document view -------------------------------------------------------------


def test_document_text_has_page_separators_and_flags():
    view = {
        "id": "D-0001",
        "read_pages": 2,
        "pages": [
            {
                "page": 1,
                "flags": [{"code": "scan_unread", "reason": "скан"}],
                "text": "Первая страница",
            },
            {"page": 2, "flags": [], "text": "Вторая страница"},
        ],
    }
    lines = render_document_text(view).splitlines()
    assert lines == [
        "── стр. 1 ──",
        "! скан, не прочитана: скан",
        "Первая страница",
        "── стр. 2 ──",
        "Вторая страница",
    ]


def test_document_text_empty_page_shows_placeholder():
    view = {
        "id": "D-0001",
        "read_pages": 1,
        "pages": [{"page": 1, "flags": [], "text": ""}],
    }
    assert render_document_text(view).splitlines() == ["── стр. 1 ──", "(нет текста)"]


# --- text --page: page view ----------------------------------------------------------


def _page_view(*, flags=(), has_table=False, lines=()) -> dict:
    return {
        "id": "D-0001",
        "pages": [
            {
                "page": 2,
                "rotation": 0,
                "has_table": has_table,
                "flags": list(flags),
                "lines": list(lines),
            }
        ],
    }


def _line(i: int, text: str, *, role: str = "body", column=None, table=None) -> dict:
    return {
        "i": i,
        "text": text,
        "bbox": [0.0, 0.0, 1.0, 1.0],
        "role": role,
        "column": column,
        "table": table,
    }


def test_page_header_is_document_and_page_number():
    text = render_page_text(_page_view())
    assert text.splitlines()[0] == "D-0001, стр. 2"


def test_page_without_flags_says_none():
    lines = render_page_text(_page_view(lines=[_line(0, "Текст")])).splitlines()
    assert lines[1] == "Флаги: нет"


def test_page_flags_are_listed_with_reasons():
    view = _page_view(flags=[{"code": "unreadable", "reason": "мусор в символах"}])
    lines = render_page_text(view).splitlines()
    assert lines[1] == "! текст не читается: мусор в символах"
    assert "Флаги: нет" not in lines


def test_table_flag_line_only_when_table_present():
    with_table = render_page_text(_page_view(has_table=True, lines=[_line(0, "x")]))
    without = render_page_text(_page_view(has_table=False, lines=[_line(0, "x")]))
    assert "Таблица: есть" in with_table.splitlines()
    assert "Таблица: есть" not in without.splitlines()


def test_page_line_markers_for_column_and_table_cell():
    lines = [
        _line(0, "Заголовок", role="header"),
        _line(1, "Левая колонка", column=1),
        _line(2, "Ячейка", table={"t": 0, "row": 2, "cell": 1}),
        _line(3, "Обычная строка"),
    ]
    rendered = render_page_text(_page_view(lines=lines)).splitlines()
    assert rendered[2:] == [
        f"  0  {'колонтитул':<10}  {'':<20}  Заголовок",
        f"  1  {'текст':<10}  {'кол. 1':<20}  Левая колонка",
        f"  2  {'текст':<10}  {'табл. 1 стр. 3 яч. 2':<20}  Ячейка",
        f"  3  {'текст':<10}  {'':<20}  Обычная строка",
    ]


def test_page_line_index_is_right_aligned_in_three_chars():
    rendered = render_page_text(_page_view(lines=[_line(12, "строка")])).splitlines()
    assert rendered[-1] == " 12  текст  строка"


def test_table_mark_indices_are_shown_one_based():
    line = _line(0, "Ячейка", table={"t": 0, "row": 0, "cell": 0})
    rendered = render_page_text(_page_view(lines=[line])).splitlines()
    assert rendered[-1] == "  0  текст  табл. 1 стр. 1 яч. 1  Ячейка"


def test_table_mark_higher_indices_are_shifted_by_one():
    line = _line(7, "Ячейка", table={"t": 1, "row": 4, "cell": 2})
    rendered = render_page_text(_page_view(lines=[line])).splitlines()
    assert "табл. 2 стр. 5 яч. 3" in rendered[-1]


def test_column_mark_shows_stored_column_as_is():
    lines = [_line(0, "Левая", column=1), _line(1, "Правая", column=2)]
    rendered = render_page_text(_page_view(lines=lines)).splitlines()
    assert "кол. 1" in rendered[-2] and "кол. 2" not in rendered[-2]
    assert "кол. 2" in rendered[-1] and "кол. 1" not in rendered[-1]


def test_role_words_for_reader():
    cases = {
        "body": "текст",
        "header": "колонтитул",
        "footer": "нижний колонтитул",
        "page_number": "номер стр.",
        "rotated": "повёрнут",
    }
    for role, word in cases.items():
        rendered = render_page_text(_page_view(lines=[_line(0, "x", role=role)]))
        assert rendered.splitlines()[-1] == f"  0  {word}  x", role


def test_rotated_line_is_marked_as_rotated():
    line = _line(4, "Вертикально", role="rotated")
    rendered = render_page_text(_page_view(lines=[line]))
    assert rendered.splitlines()[-1] == "  4  повёрнут  Вертикально"


def test_page_line_alignment_pads_role_and_marker_columns():
    lines = [
        _line(0, "Заголовок", role="header"),
        _line(1, "Левая колонка", column=1),
        _line(2, "Ячейка", table={"t": 0, "row": 2, "cell": 1}),
        _line(3, "Обычная строка"),
    ]
    rendered = render_page_text(_page_view(lines=lines)).splitlines()
    assert rendered[2:] == [
        "  0  колонтитул  " + " " * 20 + "  Заголовок",
        "  1  текст       кол. 1" + " " * 14 + "  Левая колонка",
        "  2  текст       табл. 1 стр. 3 яч. 2  Ячейка",
        "  3  текст       " + " " * 20 + "  Обычная строка",
    ]


def test_no_marker_padding_when_no_line_has_a_marker():
    lines = [_line(0, "Заголовок", role="header"), _line(1, "Текст")]
    rendered = render_page_text(_page_view(lines=lines)).splitlines()
    assert rendered[-2:] == [
        "  0  колонтитул  Заголовок",
        "  1  текст       Текст",
    ]


def test_table_flag_with_page_without_lines():
    rendered = render_page_text(_page_view(has_table=True)).splitlines()
    assert rendered == ["D-0001, стр. 2", "Флаги: нет", "Таблица: есть", "(строк нет)"]


def test_empty_page_shows_no_lines_placeholder():
    lines = render_page_text(_page_view()).splitlines()
    assert lines == ["D-0001, стр. 2", "Флаги: нет", "(строк нет)"]


def test_render_find_text_matches_and_none() -> None:
    view = {"id": "D-0001", "phrase": "x", "matches": [
        {"page": 2, "line": 5, "role": "body", "context": "до x после"},
        {"page": 1, "line": 0, "role": "header", "context": "x"},
    ]}
    assert render_find_text(view).splitlines() == [
        "стр. 2, строка 5, body: …до x после…",
        "стр. 1, строка 0, header: …x…",
    ]
    assert render_find_text({"id": "D-0001", "phrase": "x", "matches": []}) == "Не найдено"
