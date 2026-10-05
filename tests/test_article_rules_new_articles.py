"""Artikel mit eigener Kalkulation (Auswahl im Abgleich) und neue Artikel unterm Jahr."""

from decimal import Decimal

from sqlalchemy import select

from backend.database.engine import session_scope
from backend.models.entities import Article, AuditLog, Manufacturer, PriceUpdateItem, Rule, RuleException
from tests.test_annual_extras import _start
from tests.test_price_update import _import, _items, _ours, _setup

D = Decimal


def test_selected_articles_get_own_factor_and_keep_it(admin_client, user_client, tmp_path, app):
    c = admin_client
    mid, rule_id = _setup(c, factor="2,6")
    ours = _ours(c, app, tmp_path, mid, [["LED1", "a", "10,00", "26,00"], ["LED2", "b", "10,00", "28,00"]])
    new = _import(c, app, tmp_path, "h", [["Artikelnummer", "Bezeichnung", "EK"], ["LED1", "a", "10,00"],
                                          ["LED2", "b", "10,00"]], mid, "HERSTELLER")
    url = _start(c, ours, new, rule_id)
    _, items = _items()
    assert items["LED2"].final_vk == D("26.00")
    page = c.get(url).text
    assert 'form="ausnahme-form"' in page
    assert user_client.get(url).status_code == 404

    r = c.post(url + "/ausnahmen", data={"csrf_token": c.csrf, "action": "setzen", "factor": "2,8"})
    assert "Keine Artikel ausgewählt" in r.text
    r = c.post(url + "/ausnahmen", data={"csrf_token": c.csrf, "action": "setzen", "factor": "abc",
                                         "item": str(items["LED2"].id)})
    assert "ungültig" in r.text
    r = c.post(url + "/ausnahmen", data={"csrf_token": c.csrf, "action": "setzen", "factor": "2,8",
                                         "item": str(items["LED2"].id)})
    assert "1 Artikel: ab jetzt Regel „RaphiLED × 2,8“" in r.text and "eigene Kalkulation" in r.text
    upd, items = _items()
    led2 = items["LED2"]
    assert led2.final_vk == D("28.00") and led2.factor == D("2.8") and led2.check_ok is True
    assert "Ausnahme Artikel „LED2“: RaphiLED × 2,8 v1" == led2.rule_label
    assert items["LED1"].final_vk == D("26.00")
    with session_scope() as db:
        ex = db.scalar(select(RuleException))
        assert (ex.match_type, ex.value_normalized, ex.manufacturer_id) == ("ARTIKEL", "LED2", mid)
        assert db.scalar(select(Rule).where(Rule.name == "RaphiLED × 2,8")) is not None
    assert c.post(url + "/ausnahmen", data={"csrf_token": c.csrf, "action": "setzen", "factor": "2,8",
                                            "item": str(led2.id)}).status_code == 200
    with session_scope() as db:
        assert len(db.scalars(select(Rule).where(Rule.name == "RaphiLED × 2,8")).all()) == 1  # wiederverwendet
    assert user_client.post(url + "/ausnahmen", data={"csrf_token": user_client.csrf, "action": "entfernen",
                                                      "item": str(led2.id)}).status_code == 404  # fremder Abgleich

    # nächstes Jahr: Ausnahme greift automatisch
    new2 = _import(c, app, tmp_path, "h2", [["Artikelnummer", "Bezeichnung", "EK"], ["LED1", "a", "10,00"],
                                            ["LED2", "b", "11,00"]], mid, "HERSTELLER")
    url2 = _start(c, ours, new2, rule_id)
    _, items2 = _items()
    assert items2["LED2"].final_vk == D("30.80")
    # zurück auf Standard
    c.post(url2 + "/ausnahmen", data={"csrf_token": c.csrf, "action": "entfernen", "item": str(items2["LED2"].id)})
    _, items2 = _items()
    assert items2["LED2"].final_vk == D("28.60") and items2["LED2"].rule_label.startswith("Standard")
    with session_scope() as db:
        assert db.scalar(select(RuleException)) is None
        assert {"artikel_ausnahme_setzen", "artikel_ausnahme_entfernen"} <= {a.action for a in db.scalars(select(AuditLog))}


def test_new_articles_detected_by_code_and_added_after_confirmation(admin_client, tmp_path, app):
    c = admin_client
    c.post("/hersteller", data={"csrf_token": c.csrf, "name": "Strand", "code": "ST"})
    with session_scope() as db:
        mid = db.scalar(select(Manufacturer)).id
    r = c.post("/regeln/neu", data={"csrf_token": c.csrf, "name": "Strand", "manufacturer_id": str(mid),
                                    "start_price": "EK", "rounding_mode": "HALF_UP", "rounding_places": "2",
                                    "rounding_timing": "STEP", "step_1_type": "multiply", "step_1_value": "2,6"},
               follow_redirects=False)
    ours = _ours(c, app, tmp_path, mid, [["LED1", "a", "10,00", "26,00"]])
    _import(c, app, tmp_path, "h", [["Artikelnummer", "Bezeichnung", "EK"], ["LED1", "a", "10,00"],
                                    ["NEW-1", "Neuheit 2026", "20,00"]], mid, "HERSTELLER")
    text = "STNEW1\nSTLED1\nXX9\nSTNOPE\nST NOPE2;Sonderteil;12,50\nstnew-1\nSTNEG;x;-3"
    page = c.post("/neue-artikel", data={"csrf_token": c.csrf, "text": text}).text
    assert "2 von 7 Zeilen aufnehmbar" in page
    assert "Steht schon in" in page and "Kein Hersteller-Kürzel erkannt" in page
    assert "Nicht in einer Herstellerliste gefunden" in page and "Doppelt eingefügt (schon in Zeile 1)" in page
    assert "keine gültige Zahl größer 0" in page
    assert "52,00" in page and "32,50" in page and "Neuheit 2026" in page

    r = c.post("/neue-artikel/aufnehmen", data={"csrf_token": c.csrf, "text": text, "line": ["1", "5", "2"]})
    assert r.status_code == 400 and "Häkchen" in r.text
    with session_scope() as db:
        assert db.scalar(select(Article).where(Article.price_list_id == ours, Article.article_number == "NOPE2")) is None
    # Zeile 2 (schon vorhanden) wird trotz Auswahl nicht aufgenommen
    r = c.post("/neue-artikel/aufnehmen", data={"csrf_token": c.csrf, "text": text, "line": ["1", "5", "2"],
                                               "bestaetigt": "ja"})
    assert "2 Artikel aufgenommen" in r.text
    with session_scope() as db:
        arts = {a.article_number: {p.price_type: p.amount for p in a.prices}
                for a in db.scalars(select(Article).where(Article.price_list_id == ours))}
        log = db.scalars(select(AuditLog).where(AuditLog.action == "neue_artikel_aufgenommen")).one()
    assert arts["NEW-1"] == {"EK": D("20.00"), "LISTE": D("52.00")}  # Nummer wie in der Herstellerliste
    assert arts["NOPE2"] == {"EK": D("12.50"), "LISTE": D("32.50")}
    assert len(arts) == 3 and len(log.details["artikel"]) == 2
    page = c.post("/neue-artikel", data={"csrf_token": c.csrf, "text": "STNEW1"}).text
    assert "Steht schon in" in page


def test_ambiguous_codes_are_not_guessed(admin_client, tmp_path, app):
    c = admin_client
    c.post("/hersteller", data={"csrf_token": c.csrf, "name": "S-Firma", "code": "S"})
    c.post("/hersteller", data={"csrf_token": c.csrf, "name": "Strand", "code": "ST"})
    page = c.post("/neue-artikel", data={"csrf_token": c.csrf, "text": "ST123"}).text
    assert "Kürzel mehrdeutig (S, ST)" in page and "0 von 1 Zeilen aufnehmbar" in page
