"""`TopicEmbedder`, the fake search model of feature 08 (research R-8; task T006).

Written by the main session: the fake decides what «close by meaning» means in the
search tests.
"""

import math

from docreader import embedding
from docreader.config import EmbeddingSettings
from tests.fakes.embedding import TopicEmbedder

TOPICS = {"payment": ["оплат", "перечисл", "деньг"], "penalty": ["неустойк"]}


def cos(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_texts_on_one_topic_are_closer_than_without_it() -> None:
    fake = TopicEmbedder(TOPICS)
    query = fake.topic_vector("куда переводить деньги")
    paraphrase = fake.topic_vector("Покупатель перечисляет денежные средства")
    other = fake.topic_vector("Приёмка проводится на складе")
    assert cos(query, paraphrase) > 0.9
    assert cos(query, paraphrase) > cos(query, other) + 0.5


def test_same_text_same_vector_and_unit_length() -> None:
    fake = TopicEmbedder(TOPICS)
    v = fake.topic_vector("за просрочку уплачивается неустойка")
    assert v == fake.topic_vector("за просрочку уплачивается неустойка")
    assert math.isclose(sum(x * x for x in v), 1.0)


def test_text_without_topics_is_a_unit_vector() -> None:
    v = TopicEmbedder(TOPICS).topic_vector("Стороны освобождаются от ответственности")
    assert math.isclose(sum(x * x for x in v), 1.0)


def test_served_through_the_embeddings_protocol() -> None:
    fake = TopicEmbedder(TOPICS)
    client = embedding.load_embedder(EmbeddingSettings(), fake.transport)
    (got,) = client.embed(["оплата в течение 30 дней"])
    want = fake.topic_vector("оплата в течение 30 дней")
    assert all(math.isclose(a, b, abs_tol=1e-9) for a, b in zip(got, want, strict=True))
    assert fake.inputs == ["оплата в течение 30 дней"]
