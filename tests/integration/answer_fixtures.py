"""Shared setup of the answer tests (feature 09; tasks T008, T009, T013, T015, T017, T019).

The synthetic contracts of `make_answer_contracts` go through `add`, `read`, `parse` and
`index` with `TopicEmbedder(ANSWER_TOPICS)`; D-0001 is `answer-a` (preamble, clauses 1.1
… 4.1, 4.1 across the page break), D-0002 is `answer-b` (no preamble). The recording
command (T017) and the level 2 test (T019) take the fakes and the passage counts of their
variants from here, so that the request to the language model is the same in both.
"""

from __future__ import annotations

from pathlib import Path

from tests.fakes.embedding import TopicEmbedder
from tests.integration.test_read import add_files
from tests.synthetic import make_pdfs as mk

ANSWER_TOPICS = {
    "payment": ["оплат", "плат"],
    "penalty": ["неустойк"],
    "warranty": ["гарант"],
    "parties": ["заказчик", "подрядчик"],
}

# Clause texts of `answer-a` the tests quote verbatim.
QUOTE_PAYMENT = "Срок оплаты товара составляет 30 дней с даты поставки."
QUOTE_PENALTY = "За просрочку поставки Поставщик уплачивает неустойку 0,1% за каждый день."
QUOTE_WARRANTY_ACROSS_PAGES = "двенадцать месяцев с даты подписания акта"
QUOTE_PARTIES = "именуемое в дальнейшем Подрядчик"


def add_answer_contracts(cli, folder: Path) -> list[str]:
    paths = mk.make_answer_contracts(folder / "made")
    makers = [lambda dst, src=p: dst.write_bytes(src.read_bytes()) for p in paths]
    return add_files(cli, folder / "in", makers)


def index_answer_contracts(cli, folder: Path, use_embedder) -> tuple[list[str], TopicEmbedder]:
    ids = add_answer_contracts(cli, folder)
    assert cli("read").exit_code == 0
    assert cli("parse").exit_code == 0
    fake = use_embedder(TopicEmbedder(ANSWER_TOPICS))
    result = cli("index")
    assert result.exit_code == 0, result.stderr
    return ids, fake
