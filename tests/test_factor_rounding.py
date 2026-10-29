"""VK-Rundung neuer Hersteller (10 Cent aufrunden) und Faktor VK/EK mit einer Nachkommastelle."""

from decimal import Decimal as D

from tests.test_e2e_szenarien import items_of, new_manufacturer, smart_page, start


def test_new_manufacturer_rounds_vk_up_to_10_cent_also_for_exceptions(admin_client, app):
    c = admin_client
    new_manufacturer(c, "Raphi LED", "RA", "2,8")
    _, page = smart_page(c, "RaphiLED_Preisliste_2026.xlsx")
    start(c, app, page)
    _, page = smart_page(c, "RaphiLED_Herstellerliste_2027.xlsx")
    assert "VK neu = EK × 2,8, auf 10 Cent (aufrunden)" in page
    target = start(c, app, page)
    items = items_of(int(target.rsplit("/", 1)[1]))
    bl2 = items["BL2"]  # EK 3,12 × 2,8 = 8,736 -> 8,74 -> 8,80
    assert (bl2.final_ek, bl2.final_vk, bl2.factor) == (D("3.12"), D("8.80"), D("2.8"))
    for i in items.values():
        if i.decision == "NEU":
            assert i.final_vk % D("0.1") == 0 and i.factor == i.factor.quantize(D("0.1")), i.article_number
            assert i.check_ok is True, i.article_number
    # „anders kalkulieren“ mit Faktor übernimmt die VK-Rundung des Herstellers
    c.post(f"{target}/ausnahmen", data={"csrf_token": c.csrf, "action": "setzen", "factor": "3",
                                        "item": str(bl2.id)})
    bl2 = items_of(int(target.rsplit("/", 1)[1]))["BL2"]
    assert (bl2.final_vk, bl2.factor, bl2.check_ok) == (D("9.40"), D("3.0"), True)  # 9,36 -> 9,40
