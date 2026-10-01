import re

from sqlalchemy import select

from backend.database.engine import session_scope
from backend.models.entities import AuditLog, ComparisonItem, Rule, RuleVersion
from tests.conftest import make_xlsx, run_jobs
from tests.test_import_web import upload


def import_list(client, tmp_path, name, rows):
    p = make_xlsx(tmp_path / f"{name}.xlsx", rows)
    list_id = int(upload(client, p).headers["location"].rsplit("/", 1)[1])
    r = client.post(f"/import/{list_id}/confirm", data={
        "csrf_token": client.csrf, "sheet": "Preise", "header_row": "1", "col_0": "article_number",
        "col_1": "description", "col_2": "list_price", "sep_2": ",", "new_manufacturer": "ACME", "currency": "EUR",
    }, follow_redirects=False)
    assert r.status_code == 303, r.text
    run_jobs(client.app)
    return list_id


RULE_FORM = {
    "name": "Händler", "start_price": "LISTE", "rounding_mode": "HALF_UP", "rounding_places": "2",
    "rounding_timing": "STEP",
    "step_1_type": "discount", "step_1_value": "15", "step_1_base": "start",
    "step_2_type": "surcharge", "step_2_value": "4", "step_2_base": "current", "step_2_label": "Transport",
}


def test_rule_create_version_test_and_delete(admin_client):
    r = admin_client.post("/regeln/neu", data={**RULE_FORM, "csrf_token": admin_client.csrf}, follow_redirects=False)
    assert r.status_code == 303
    rule_id = int(r.headers["location"].rsplit("/", 1)[1])
    r = admin_client.post(f"/regeln/{rule_id}/test", data={"csrf_token": admin_client.csrf, "amount": "100,00",
                                                           "quantity": "1"})
    assert "88,40" in r.text and "3,40" in r.text
    # Änderung erzeugt v2, v1 bleibt
    r = admin_client.post(f"/regeln/{rule_id}", data={**RULE_FORM, "step_1_value": "20", "comment": "mehr Rabatt",
                                                      "csrf_token": admin_client.csrf}, follow_redirects=False)
    assert r.status_code == 303
    with session_scope() as db:
        versions = db.scalars(select(RuleVersion).where(RuleVersion.rule_id == rule_id)).all()
        assert [v.version for v in versions] == [1, 2]
        assert versions[0].definition["steps"][0]["percent"] == "15"
        assert versions[1].definition["steps"][0]["percent"] == "20"
    page = admin_client.get(f"/regeln/{rule_id}?version=1").text
    assert "Version 1" in page
    admin_client.post(f"/regeln/{rule_id}/loeschen", data={"csrf_token": admin_client.csrf})
    assert admin_client.get(f"/regeln/{rule_id}").status_code == 404
    with session_scope() as db:
        assert db.get(Rule, rule_id).deleted
        assert {"regel_angelegt", "regel_geaendert", "regel_geloescht"} <= set(db.scalars(select(AuditLog.action)))


def test_rule_validation_errors(admin_client):
    r = admin_client.post("/regeln/neu", data={**RULE_FORM, "step_1_value": "150", "step_3_type": "formula",
                                               "step_3_value": "__import__('os')", "csrf_token": admin_client.csrf})
    assert r.status_code == 400
    assert "Schritt 1" in r.text and "Schritt 3" in r.text


def test_user_cannot_edit_rules(user_client):
    assert user_client.get("/regeln/neu").status_code == 403
    r = user_client.post("/regeln/neu", data={**RULE_FORM, "csrf_token": user_client.csrf})
    assert r.status_code == 403


def test_calculation_and_comparison_flow(admin_client, tmp_path):
    old = import_list(admin_client, tmp_path, "alt", [
        ["Art.-Nr.", "Bezeichnung", "Listenpreis"],
        ["A-1", "Schraube", "100,00"], ["A-2", "Mutter", "10,00"], ["GONE", "Weg", "1,00"],
        ["ABC-1000", "Spezialteil Typ X", "5,00"],
    ])
    new = import_list(admin_client, tmp_path, "neu", [
        ["Art.-Nr.", "Bezeichnung", "Listenpreis"],
        ["A-1", "Schraube", "110,00"], ["a2", "Mutter", "10,00"], ["NEW", "Neu", "2,00"],
        ["ABC-1001", "Spezialteil Typ X", "6,00"],
    ])
    r = admin_client.post("/regeln/neu", data={**RULE_FORM, "csrf_token": admin_client.csrf}, follow_redirects=False)
    rule_id = int(r.headers["location"].rsplit("/", 1)[1])

    r = admin_client.post(f"/listen/{old}/kalkulation", data={"csrf_token": admin_client.csrf, "rule_id": rule_id,
                                                              "quantity": "1"}, follow_redirects=False)
    assert r.status_code == 303
    page = admin_client.get(r.headers["location"]).text
    assert "88,40" in page and "Händler v1" in page

    r = admin_client.post("/vergleiche", data={"csrf_token": admin_client.csrf, "old_id": old, "new_id": new,
                                               "price_type": "LISTE", "quantity": "1"}, follow_redirects=False)
    assert r.status_code == 303
    cmp_url = r.headers["location"]
    cmp_id = int(cmp_url.rsplit("/", 1)[1])
    page = admin_client.get(cmp_url).text
    for label in ("erhöht", "entfallen", "nicht eindeutig"):
        assert label in page
    with session_scope() as db:
        items = {i.article_number: i for i in db.scalars(select(ComparisonItem).where(ComparisonItem.comparison_id == cmp_id))}
    assert items["A-1"].status == "PREIS_ERHOEHT" and str(items["A-1"].difference_percent) == "10.00"
    assert items["a2"].status == "UNVERAENDERT" and items["a2"].match_method == "NORMALISIERT"
    assert items["NEW"].status == "NEUER_ARTIKEL" and items["GONE"].status == "ENTFALLENER_ARTIKEL"
    unclear = items["ABC-1001"]
    assert unclear.status == "NICHT_EINDEUTIG"

    # Filter
    data = admin_client.get(f"{cmp_url}?status=UNKLAR").text
    assert "ABC-1001" in data and "A-1</td>" not in data
    data = admin_client.get(f"{cmp_url}?pmin=50").text
    assert "Schraube" in data and "Mutter" not in data

    # Zuordnung bestätigen
    r = admin_client.post(f"/vergleiche/{cmp_id}/eintrag/{unclear.id}",
                          data={"csrf_token": admin_client.csrf, "old_id": unclear.candidates[0]["old_id"]},
                          follow_redirects=False)
    assert r.status_code == 303
    with session_scope() as db:
        st = {i.article_number: (i.status, i.match_method) for i in
              db.scalars(select(ComparisonItem).where(ComparisonItem.comparison_id == cmp_id))}
    assert st["ABC-1001"] == ("PREIS_ERHOEHT", "BESTAETIGT")

    # Kalkulierter Vergleich
    r = admin_client.post("/vergleiche", data={"csrf_token": admin_client.csrf, "old_id": old, "new_id": new,
                                               "price_type": "KALKULIERT", "rule_id": rule_id, "quantity": "1"},
                          follow_redirects=False)
    assert r.status_code == 303
    assert "88,40" in admin_client.get(r.headers["location"]).text


def test_comparison_form_errors(admin_client):
    r = admin_client.post("/vergleiche", data={"csrf_token": admin_client.csrf, "price_type": "KALKULIERT"})
    assert r.status_code == 400 and "Alte und neue Liste" in r.text and "Regel" in r.text


def test_manufacturer_settings(admin_client, user_client):
    r = admin_client.post("/hersteller", data={"csrf_token": admin_client.csrf, "name": "Bosch",
                                               "aliases": "Robert Bosch; BOSCH GmbH"}, follow_redirects=False)
    assert r.status_code == 303
    page = admin_client.get("/hersteller").text
    assert "Robert Bosch; BOSCH GmbH" in page
    mid = re.search(r'name="id" value="(\d+)"', page).group(1)
    admin_client.post("/hersteller", data={"csrf_token": admin_client.csrf, "id": mid, "name": "Bosch", "aliases": ""})
    assert "checked" not in admin_client.get("/hersteller").text.split("Hersteller anlegen")[0]
    assert user_client.post("/hersteller", data={"csrf_token": user_client.csrf, "name": "X"}).status_code == 403
