import pytest
from scalesync_bridge.parsers.ohaus import OhausParser


@pytest.fixture
def parser():
    return OhausParser()


# ── PCS counting-mode lines (confirmed protocol) ──────────────────────────────

def test_pcs_stable(parser):
    r = parser.parse("3   PCS")
    assert r is not None
    assert r.piece_count == 3
    assert r.unit == "PCS"
    assert r.stable is True
    assert r.weight_g is None


def test_pcs_unstable(parser):
    r = parser.parse("3   PCS ?")
    assert r is not None
    assert r.piece_count == 3
    assert r.stable is False


def test_pcs_zero(parser):
    r = parser.parse("0   PCS")
    assert r is not None
    assert r.piece_count == 0
    assert r.stable is True


def test_pcs_large_count(parser):
    r = parser.parse("1234   PCS")
    assert r is not None
    assert r.piece_count == 1234


def test_pcs_extra_spaces(parser):
    r = parser.parse("  7   PCS  ")
    assert r is not None
    assert r.piece_count == 7


# ── Comma-format weight lines ─────────────────────────────────────────────────

def test_comma_stable_grams(parser):
    r = parser.parse("ST,GS,  125.43,g")
    assert r is not None
    assert r.weight_g == pytest.approx(125.43)
    assert r.unit == "g"
    assert r.stable is True
    assert r.piece_count is None


def test_comma_unstable_grams(parser):
    r = parser.parse("US,GS,  125.43,g")
    assert r is not None
    assert r.stable is False


def test_comma_stable_pcs(parser):
    r = parser.parse("ST,N,     3,PCS")
    assert r is not None
    assert r.piece_count == 3
    assert r.unit == "PCS"
    assert r.stable is True


def test_comma_zero_weight(parser):
    r = parser.parse("ST,GS,  0.00,g")
    assert r is not None
    assert r.weight_g == pytest.approx(0.0)


# ── Simple gram/lb format ─────────────────────────────────────────────────────

def test_simple_lb(parser):
    r = parser.parse("  +  125.43 lb")
    assert r is not None
    assert r.weight_g == pytest.approx(125.43)
    assert r.unit == "lb"
    assert r.stable is True


def test_simple_zero(parser):
    r = parser.parse("     0.0000    lb")
    assert r is not None
    assert r.weight_g == pytest.approx(0.0)


# ── Invalid / empty lines ─────────────────────────────────────────────────────

def test_empty_line(parser):
    assert parser.parse("") is None


def test_whitespace_only(parser):
    assert parser.parse("   ") is None


def test_garbage(parser):
    assert parser.parse("???") is None


def test_partial_comma(parser):
    assert parser.parse("ST,GS") is None
