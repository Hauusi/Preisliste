# Datenblatt-Regeln: Hersteller → Braun & Braun

Abgeleitet aus Vergleichspaaren (Herstellerblatt ↔ B&B-Blatt desselben Produkts). Grundlage für den Import
(`backend/services/datasheet_import.py`). Neue Paare hier ergänzen, bevor Regeln im Code geändert werden.

Vergleichspaare bisher:

| Hersteller | Herstellerblatt | B&B-Blatt |
|---|---|---|
| Strands (englisch) | Unity Work Light 31W, Part No. 809237 (ein Modell) | LED Scheinwerfer – Serie Unity (7 Modelle, 2 Seiten) |
| ECCO (englisch) | 400 Series R65 LED Beacons (8 Montagevarianten) | LED Rundumleuchten / Blitzleuchten – Serie 400 (3 Artikel) |
| Nordic Lights (deutsch) | Scorpius GO 410 | (kein B&B-Blatt, nur Importtest) |

## 1. Aufbau und Platzierung

| B&B-Blatt | Woher |
|---|---|
| Titel oben rechts: Produktart Plural, „LED“ davor („LED SCHEINWERFER“, „LED RUNDUMLEUCHTEN“) | Produktart aus Herstellerblatt (Rubrik „BEACONS“, „WORK LIGHT“) |
| Untertitel „SERIE …“ – nur Serienname, ohne Modell/Leistung/Teilenummer | „Unity Work Light 31W“ → „Serie Unity“; „400 Series“ → „Serie 400“ |
| Text oben links, 4–6 Sätze, eigene Formulierung (nicht übersetzt, keine Werbefloskeln wie „revolutionary“) | Herstellertext nur als Faktenquelle |
| 1–2 Aufzählungspunkte: zuerst „3 Jahre Garantie“, dann ein Ausstattungsmerkmal („20-52cm Anschlusskabel mit Deutsch Stecker“) | Garantie steht beim Hersteller oft nur als Logo („3 YEAR“) – im Text nicht auslesbar |
| Spezifikation links unter dem Text: Überschrift „PRODUKTART - SERIE X“ + „SPEZIFIKATIONEN“, Zulassungslogos, dann feste Zeilen | Datentabelle des Herstellers |
| Bilder rechts: Produktfotos (Unity: alle Modelle einzeln), bei Rundumleuchten zusätzlich Maßzeichnung und Montagevarianten mit Bildunterschrift („Magnetmontage ø 200 x 156mm, Doppelblitz“) | Herstellerbilder |
| Anwendungsfotos unten (Unity: 2 nebeneinander) bzw. großes Gruppenfoto über der Bestelltabelle | Herstellerbilder |
| Tabelle „BESTELLINFORMATIONEN - SERIE X“: kleines Bild, Artikel, (Farbpunkt), Beschreibung, ggf. Zusatzspalte (Lumen) | Modelltabelle des Herstellers |

## 2. Spezifikation: feste Zeilen und Quellen

Reihenfolge immer: Spannungsbereich, Lichtleistung, Wasserdicht, Montage, Zulassungen, Gehäuse, Abmessungen, Leuchtbild.
Zeilen ohne Angabe beim Hersteller entfallen (ECCO: keine Lichtleistung, kein Leuchtbild).

| B&B | Englisch beim Hersteller | Beispiel Hersteller → B&B |
|---|---|---|
| Spannungsbereich | Voltage (DC), Voltage, Operating voltage | „10-40 V DC“ → „10-32V“ *(siehe offene Fragen)*; „10-30V“ → „10-30V“ |
| Lichtleistung | Actual lumen, Raw lumen, Luminous flux | Serie: Spanne „1.520 - 21.600lm (931 - 13.000lm gemessen)“ – theoretisch zuerst, gemessen in Klammern |
| Wasserdicht | IP-class, IP rating | „IP67/69K“ → „IP67 & IP69k“; keine IP-Angabe → „✓“ (ECCO) |
| Montage | Mount, Mounting | „3 Bolt / 1 Bolt“ → „Fixmontage“, „Mag 50/70“ → „Magnetmontage“, „Flexi DIN Pole“ → „flexible Rohrmontage“, „DIN Pole“ → „Rohrmontage“, Schraube allgemein → „Schraubmontage“; mehrere: „Fix-, Magnet-, flexible Rohrmontage“ |
| Zulassungen | ECE approval, Approvals, „R65“/„R10“-Logos | „R10.06“ → „ECE-R10“; Logos R65/R10 → „ECE-R65, ECE-R10“; Sonderfall mit Artikel: „ECE-R23 (ST809234)“. „E-approved: No“ entfällt |
| Gehäuse | Material housing/chassi, Housing | „Aluminium“ → „Aluminium“; Kunststoff/Polycarbonat → „Kunststoff“ |
| Abmessungen | Dimensions (oft nur Zeichnung) | „ø 153 x 143mm“; Serie: je Artikel eine Zeile „70 x 96 x 41mm (809237)“ |
| Leuchtbild | Beam pattern | „Flood beam“ → „Flood“ (Begriffe Flood/Spot/Wide Flood bleiben englisch) |

**Nicht** übernommen werden (Unity): Consumption, Functions, 1 lux @ m, Color temperature, Operating temperature,
Color lens, Material lens, Connection/Cable length (wandern in Aufzählung bzw. Artikelbeschreibung).
ECCO: Flash-Pattern-Liste (wird zu „7 Funktionen“ / „Doppelblitz“ in Text und Beschreibung).

## 3. Schreibweise

- Einheiten ohne Leerzeichen: „10-30V“, „31W“, „52cm“, „143mm“, „1.520lm“.
- Tausenderpunkt: „21.600lm“.
- Bereiche mit Bindestrich ohne Leerzeichen: „10-32V“; Spannen in Lichtleistung mit „ - “.
- Maße „B x H x T mm“, rund „ø D x H mm“.
- Mehrere Werte: „&“ bei IP („IP67 & IP69k“), sonst Komma.

## 4. Artikelbeschreibung

Muster: **Produktart Singular**, Ausstattung, Spannung, Leistung/Montage, Funktion – mit Komma getrennt.

- Unity: „LED Scheinwerfer, mit 52cm Anschlusskabel & Deutsch Stecker, 10-32V, 31W“ (+ Spalte Lumen „2.750lm“)
- Abweichende Art je Artikel: „LED Rückfahrscheinwerfer, …“ (ST809234)
- ECCO: „LED Blitzleuchte, gelbe Linse, 10-30V, Fixmontage, 7 Funktionen, Synchron- oder Wechselbetrieb“
- Artikelnummer mit Herstellerkürzel: Strands „ST809237“, ECCO „VA“ + „V11050“ = „VAV11050“
- B&B nimmt nicht jede Variante auf (ECCO: 3 von 8).

## 5. Wörterbuch Englisch → B&B

| Englisch | B&B |
|---|---|
| work light, worklight | Scheinwerfer *(siehe offene Fragen)* |
| reversing light, reverse light | Rückfahrscheinwerfer |
| beacon (rotierend) | Rundumleuchte |
| beacon (blitzend), flash beacon, strobe | Blitzleuchte *(siehe offene Fragen)* |
| amber | gelb (Linse: „gelbe Linse“) |
| clear | klar |
| bolt mount, 1/3 bolt | Fixmontage |
| magnetic, mag | Magnetmontage |
| DIN pole, pole mount | Rohrmontage |
| flexi DIN pole | flexible Rohrmontage |
| DT-2PIN, Deutsch connector | Deutsch Stecker |
| cable length 520 mm | 52cm Anschlusskabel |
| double flash | Doppelblitz |
| single flash | Einzelblitz |
| steady burn | Dauerlicht |
| synchronised / alternating | Synchron- / Wechselbetrieb |
| flood beam | Flood |
| aluminium, die-cast aluminium | Aluminium |
| polycarbonate (Gehäuse) | Kunststoff |
| X year warranty | X Jahre Garantie |

## 6. Offene Fragen (vom Besitzer zu klären)

1. **Work light:** B&B schreibt bei Unity „LED Scheinwerfer“, der Import macht bisher „LED Arbeitsscheinwerfer“
   (Scorpius). Welche Bezeichnung gilt?
2. **ECCO 400:** Titel „LED RUNDUMLEUCHTEN“, Spezifikation und Beschreibung „LED Blitzleuchte(n)“, Dateiname
   „Blitzleuchten“. Was ist richtig für blitzende LED-Beacons?
3. **Spannung Unity:** Hersteller „10-40 V DC“, B&B „10-32V“. Bewusst eingeschränkt oder aus anderer Quelle?
4. **Lumen Unity 809237:** Hersteller „Actual lumen 2200 lm“, B&B-Tabelle „2.750lm“. Welche Quelle gilt
   (theoretisch/gemessen)?
