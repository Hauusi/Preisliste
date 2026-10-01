from backend.matching.cascade import Item, match, strip_zeros


def it(i, num, mfr=1, desc=None, norm=None):
    from backend.excel.importer import normalize_article_number
    return Item(i, mfr, num, norm or normalize_article_number(num), desc)


def test_strip_zeros_only_numeric():
    assert strip_zeros("00123") == "123"
    assert strip_zeros("000") == "0"
    assert strip_zeros("00A1") == "00A1"


def test_cascade_stages():
    old = [it(1, "A-100"), it(2, "b 200"), it(3, "00123"), it(4, "X1")]
    new = [it(11, "A-100"), it(12, "B-200"), it(13, "123"), it(14, "Y9")]
    r = match(old, new, ignore_zeros={1})
    methods = {(o, n): m for o, n, m, _ in r.pairs}
    assert methods == {(1, 11): "EXAKT", (2, 12): "NORMALISIERT", (3, 13): "NULLEN"}
    assert r.new_only == [14] and r.old_only == [4]


def test_leading_zeros_disabled_per_manufacturer():
    r = match([it(1, "00123")], [it(2, "123")], ignore_zeros=set())
    assert r.pairs == []


def test_manufacturer_separates():
    r = match([it(1, "A1", mfr=1)], [it(2, "A1", mfr=2)])
    assert r.pairs == [] and r.new_only == [2] and r.old_only == [1]


def test_duplicates_are_unclear():
    r = match([it(1, "A1"), it(2, "A1")], [it(3, "A1")])
    assert r.pairs == []
    assert [c.old_id for c in r.unclear[3]] == [1, 2]
    assert r.old_only == []


def test_fuzzy_is_only_suggestion():
    old = [it(1, "ABC-1000", desc="Schraube M6 verzinkt"), it(2, "ZZZ", desc="Etwas anderes")]
    new = [it(3, "ABC-1001", desc="Schraube M6 verzinkt")]
    r = match(old, new)
    assert r.pairs == []
    assert r.unclear[3][0].old_id == 1
    assert r.old_only == [2]  # Kandidat 1 gilt nicht als entfallen


def test_decisions_confirm_and_reject():
    old = [it(1, "ABC-1000", desc="Schraube")]
    new = [it(3, "ABC-1001", desc="Schraube")]
    r = match(old, new, decisions={(1, "ABC1000", "ABC1001"): "MATCH"})
    assert r.pairs == [(1, 3, "BESTAETIGT", 100)]
    r = match(old, new, decisions={(1, "ABC1000", "ABC1001"): "NO_MATCH"})
    assert r.pairs == [] and r.unclear == {} and r.new_only == [3] and r.old_only == [1]
