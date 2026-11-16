import pytest

from docreader.pdfpages import union_area

CLIP = (0.0, 0.0, 10.0, 10.0)


def test_no_rects():
    assert union_area([], CLIP) == pytest.approx(0.0)


def test_single_rect_inside():
    assert union_area([(1.0, 1.0, 4.0, 3.0)], CLIP) == pytest.approx(6.0)


def test_overlapping_rects_counted_once():
    rects = [(0.0, 0.0, 2.0, 2.0), (1.0, 1.0, 3.0, 3.0)]
    assert union_area(rects, CLIP) == pytest.approx(7.0)


def test_rect_partly_outside_is_clipped():
    assert union_area([(8.0, 8.0, 15.0, 15.0)], CLIP) == pytest.approx(4.0)


def test_rect_fully_outside():
    assert union_area([(20.0, 20.0, 30.0, 30.0)], CLIP) == pytest.approx(0.0)


def test_strips_cover_clip_exactly():
    strips = [(0.0, float(i * 2), 10.0, float(i * 2 + 2)) for i in range(5)]
    assert union_area(strips, CLIP) == pytest.approx(100.0)


def test_nested_rect_counts_outer_only():
    rects = [(1.0, 1.0, 9.0, 9.0), (2.0, 2.0, 5.0, 5.0)]
    assert union_area(rects, CLIP) == pytest.approx(64.0)


def test_degenerate_rect_has_zero_area():
    assert union_area([(3.0, 1.0, 3.0, 8.0)], CLIP) == pytest.approx(0.0)
