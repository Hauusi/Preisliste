# Sales Assistant – Handbuch

Stand: 28.10.2026. Gilt für den Branch `ccr-71bf8639-od7ces` (der Stand, den der Server zieht).

Dieses Handbuch beschreibt das ganze Tool: zuerst die Bedienung (Teil A), dann Betrieb und Wartung (Teil B),
zuletzt die Technik für Entwickler (Teil C). Wer nur damit arbeitet, braucht Teil A.

---

## Inhalt

- [Teil A – Bedienung](#teil-a--bedienung)
  - [1. Überblick](#1-überblick)
  - [2. Anmelden, Konto, Rollen](#2-anmelden-konto-rollen)
  - [3. Modul Preisliste: der Jahresablauf](#3-modul-preisliste-der-jahresablauf)
  - [4. Hersteller einrichten](#4-hersteller-einrichten)
  - [5. Liste einspielen (Import)](#5-liste-einspielen-import)
  - [6. Jahresabgleich prüfen und abschließen](#6-jahresabgleich-prüfen-und-abschließen)
  - [7. Neue Artikel unterm Jahr](#7-neue-artikel-unterm-jahr)
  - [8. Preislisten ansehen und exportieren](#8-preislisten-ansehen-und-exportieren)
  - [9. Regeln, Kalkulationen, Vergleiche](#9-regeln-kalkulationen-vergleiche)
  - [10. KI-Funktionen](#10-ki-funktionen)
  - [11. Modul Datenblatt erstellen](#11-modul-datenblatt-erstellen)
  - [12. Modul Vertriebswissen](#12-modul-vertriebswissen)
  - [13. Verwaltung (Administratoren)](#13-verwaltung-administratoren)
  - [14. Häufige Fragen und Fehlerbilder](#14-häufige-fragen-und-fehlerbilder)
- [Teil B – Betrieb](#teil-b--betrieb)
- [Teil C – Technik](#teil-c--technik)
- [Glossar](#glossar)

---

# Teil A – Bedienung

## 1. Überblick

Der **Sales Assistant** läuft im Browser unter `https://salesassistent.duckdns.org` (Chrome, Edge oder Firefox).
Nach der Anmeldung erscheint die Startseite mit Kacheln:

| Kachel | Wofür |
|---|---|
| **Preisliste** | Herstellerlisten einspielen, EK/VK kalkulieren, Jahresabgleich prüfen, Excel exportieren |
| **Datenblatt erstellen** | Produktdatenblätter im festen Firmenlayout Schritt für Schritt erstellen, als PDF speichern |
| **Vertriebswissen** | Wissen zu Herstellern und Artikelgruppen (Mindestmengen, Bezugswege, Kalkulationshinweise, Pflicht-Zubehör) für alle eintragen und schnell finden |
| **Weitere Tools** | Platzhalter für künftige Module |
| **Verwaltung** | nur Administratoren: Benutzer, Passwörter, Protokoll |

Grundsätze, die überall gelten:

- **Nichts wird geraten.** Ist etwas unklar (Spalte, Hersteller, Währung, Zuordnung), zeigt das Tool einen Hinweis
  oder blockiert, statt still eine Annahme zu treffen.
- **Geld wird exakt gerechnet** (Dezimalzahlen, keine Rundungsfehler), jeder VK wird unabhängig ein zweites Mal
  nachgerechnet („Gegenrechnung“).
- **Jeder sieht nur seine eigenen Daten.** Administratoren sehen alles.
- **Alles wird protokolliert** (wer hat wann was importiert, geprüft, übernommen, gelöscht).
- **Die KI ist optional** und macht nur Vorschläge, die man bestätigen muss.

## 2. Anmelden, Konto, Rollen

- **Anmelden:** Benutzername und Passwort. Nach 5 Fehlversuchen ist das Konto 15 Minuten gesperrt. Pro IP-Adresse
  sind höchstens 20 Versuche in 15 Minuten möglich.
- **Sitzung:** endet nach 8 Stunden ohne Aktivität, spätestens nach 72 Stunden.
- **Passwort ändern:** oben rechts auf den Benutzernamen → „Konto“. Mindestens 12 Zeichen. Danach werden alle
  anderen Sitzungen abgemeldet.
- **Rollen:**
  - *Benutzer*: eigene Hersteller, Regeln, Listen, Abgleiche, Vergleiche, Datenblätter.
  - *Marketing*: wie Benutzer, zusätzlich Datenblätter **freigeben** (sieht dafür alle Datenblätter; fremde nur
    ansehen, nicht bearbeiten oder löschen).
  - *Administrator*: zusätzlich alles von allen Benutzern sehen und bearbeiten, Benutzer verwalten, Protokoll,
    Datenblätter freigeben.

## 3. Modul Preisliste: der Jahresablauf

```
1. Hersteller anlegen (einmalig)  →  Name, Kürzel, Faktor
2. Unsere EK/VK-Liste einspielen (einmalig)  →  wird die „aktuelle Liste“
3. Neue Herstellerliste einspielen (jedes Jahr)  →  Abgleich startet automatisch
4. Auffälligkeiten prüfen  →  bestätigen, VK von Hand, anders kalkulieren
5. Abschließen  →  neue aktuelle Liste + Excel-Download (+ Preisänderungsliste für Kunden)
```

Die Übersichtsseite (**Preisliste → Übersicht**) zeigt:

- **Zu erledigen:** offene Prüfungen, nicht abgeglichene Herstellerlisten, fehlende Regeln, unfertige Importe –
  jeweils mit Knopf zum nächsten Schritt.
- **Kennzahlen:** Hersteller, Artikel in den aktuellen Listen, offene Prüfungen.
- **So funktioniert's** (solange noch nicht alles eingerichtet ist): die drei Schritte Hersteller anlegen, unsere
  Liste einspielen, Herstellerliste einspielen – erledigte Schritte mit Haken.
- **System** (nur Administratoren): KI-Status, Speicher, laufende Jobs.
- **Herstellerkacheln:** aktuelle Liste, Stand, Ø EK- und VK-Änderung des letzten Abgleichs, Status.

## 4. Hersteller einrichten

Menü **Hersteller** → Name und Kürzel eingeben → „Anlegen“, danach die Einstellungen öffnen.

| Feld | Bedeutung |
|---|---|
| **Name** | pro Benutzer eindeutig |
| **Kürzel** | 1–10 Zeichen A–Z/0–9, pro Benutzer eindeutig. Steht in Anzeige und Export direkt vor der Artikelnummer (Kürzel `NL` + `984-9020` = `NL984-9020`). Gespeichert wird die Nummer **ohne** Kürzel. |
| **Aliase** | weitere Schreibweisen des Namens (mit `;` getrennt), helfen bei der Erkennung |
| **Faktor** | Standardkalkulation: **VK = EK × Faktor**, z. B. 2,8. Legt automatisch die Regel „<Hersteller> Standard“ an. Jede Änderung erzeugt eine neue Regelversion. |
| **VK-Rundung** | **Standard bei neuen Herstellern: auf 10 Cent aufrunden** (8,736 → 8,80). Weitere: keine (Cent) · auf 10 Cent · auf volle Euro · auf ,90 / ,95 / ,99 (Endungen runden immer **auf**, die Marge sinkt also nie). Gilt auch für „Kalk“ und „anders kalkulieren“. Bestehende Hersteller behalten ihre Einstellung. |
| **Herstellerliste enthält** | **EK** (Einkaufspreis direkt) oder **UVP** (dann ist der **Händlerrabatt** Pflicht: EK = UVP − Rabatt %) |
| **Währung der Herstellerliste** | EUR, USD, CHF, SEK, NOK, DKK, GBP, PLN, CZK. Bei Fremdwährung ist der **Umrechnungskurs** Pflicht (1 SEK = 0,095 EUR). Unsere eigene Liste ist immer in Euro. |
| **Prüfschwelle %** | ab dieser EK-Änderung (Standard 5 %, Erhöhung oder Senkung) muss ein Artikel im Abgleich geprüft werden |
| **Führende Nullen ignorieren** | rein numerische Nummern: `00123` = `123` |

**Ausnahmen (andere Kalkulation für einzelne Artikel):**

- **Spalte „Kalk“ in unserer Liste** (empfohlen): Faktor je Artikel, z. B. 2,7. Leer = Standardregel. Die Kalk
  wird beim Abgleich angewendet (gleiche Rundung wie der Standard) und in die neue Liste übernommen.
- **Im Jahresabgleich:** Artikel anhaken → „anders kalkulieren“ mit Faktor oder Regel. Gilt dauerhaft.
- **Auf der Herstellerseite:** Ausnahme „Artikelnummer ist …“ oder „Artikelnummer beginnt mit …“ mit eigener Regel.
  Nach dem Speichern zeigt das Tool, auf wie viele vorhandene Artikel sie passt (Tippfehler sofort sichtbar).

Reihenfolge, welche Kalkulation gilt: einzelner Artikel (Ausnahme) → Kalk aus unserer Liste → Nummernanfang /
Serie → Standardregel. Passen mehrere Ausnahmen mit verschiedenen Regeln, wird nicht geraten: Fehler.

Ein Hersteller lässt sich erst löschen, wenn keine Preisliste mehr Artikel von ihm enthält.

## 5. Liste einspielen (Import)

Menü **Liste einspielen** (oder Knopf auf der Übersicht) → `.xlsx`-Datei wählen oder hineinziehen.

**Angenommen:** nur `.xlsx`, höchstens 25 MB (entpackt 300 MB). **Abgelehnt:** `.xls` (altes Format), Dateien mit
Makros (`.xlsm`, `.xlsb`), beschädigte Dateien. Formeln werden nie ausgeführt; es zählt der in Excel gespeicherte
Wert. Fehlt dieser („Formel ohne gespeichertes Ergebnis“), Datei in Excel öffnen und speichern.

### Die Prüfseite

Nach dem Hochladen erkennt das Tool selbst und zeigt zur Kontrolle:

| Erkannt | Wie |
|---|---|
| **Tabellenblatt** | das Blatt mit Artikelnummer und Preis (Deckblätter werden übersprungen) |
| **Kopfzeile, Spalten** | über die Synonymliste `config/header_synonyms.yaml` (z. B. „Art.-Nr.“, „Item #“, „NET“, „Netto EK“, „UVP“, „MSRP“, „Kalk“), danach Heuristik |
| **Hersteller** | Name im Dateinamen/in der Datei, sonst Kürzel vor den Nummern (≥ 80 % der Nummern), sonst Kürzel als Wort im Dateinamen |
| **Art der Liste** | EK **und** VK vorhanden → „Unsere Liste“, sonst „Herstellerliste“ |
| **Währung** | aus Spaltenüberschriften/Titelzeilen, sonst Hersteller-Einstellung |
| **Kürzel in den Nummern** | stehen die Nummern schon mit Kürzel in der Datei, wird es beim Speichern abgeschnitten |
| **Teilliste** | enthält die Herstellerliste weniger als die Hälfte unserer Artikel, wird „Teilliste“ (Preiserhöhung einzelner Serien) vorgeschlagen |

Alles lässt sich auf der Seite umstellen (Hersteller, Art, Währung, Kürzel, Umfang). „**Spalten anpassen**“ öffnet
die Detailzuordnung. **Blockierende Punkte** (rot) müssen behoben sein, bevor „Starten“ geht, z. B. fehlende
EK-/VK-Spalte, unbekannter Hersteller, Währung passt nicht zur Hersteller-Einstellung, fehlender Kurs, mehrdeutige
Preisspalte. Hinweise (gelb/grau) sind Information.

Besonderheiten:

- Ein **neuer Hersteller** kann direkt auf der Prüfseite angelegt werden (Name, Kürzel, Faktor).
- Ein gewählter Hersteller gilt für die ganze Datei; eine Marken-/Herstellerspalte wird dann ignoriert.
- Herstellerliste mit nur einer „Preis“-Spalte: gelesen als EK bzw. UVP laut Hersteller-Einstellung.
- Mehrere Währungsspalten derselben Preisart: es gilt die gewählte Währung, die anderen werden genannt.
- In unserer Liste wird eine Rabattspalte (z. B. „-60 %“ zwischen Brutto- und Netto-EK) ignoriert, weil unsere
  Liste den fertigen Netto-EK enthält. In Herstellerlisten wird „Kalk“ nie gelesen.
- Zwei Preisspalten derselben Art (z. B. EK 2025 und EK 2026): Die Datei wird in zwei Listen geteilt und
  automatisch verglichen (älteres Jahr bzw. linke Spalte = alt).

### Was beim Import geprüft wird

Jede Zeile bekommt einen Status **OK / WARNUNG / UNKLAR / FEHLER**, Details unter „Meldungen“ der Liste:
fehlende Artikelnummer oder Preis, negativer Preis, Preis 0, unbekannte Währung, **mehrdeutige Zahl** („1.234“ –
deutsch oder englisch? wird nur mit eindeutigem Trennzeichen der Spalte aufgelöst), doppelte Artikelnummer,
Staffelzeilen (gleiche Nummer, verschiedene Mengen werden zu Staffelpreisen zusammengefasst), „entfällt“-Vermerke
des Herstellers (Information statt Fehler), Kalk außerhalb 0–100.

Zahlen: „1.234,56 €“, „1234.56“, „1 234,56“, „CHF 1'234.50“ werden erkannt. Excel-Rechenreste wie
81,60000000000001 werden wie in Excel als 81,6 gelesen.

### Nach dem Start

Der Import läuft als **Hintergrundjob** (Seite mit Fortschritt, abbrechbar; nur Status und Fortschritt werden alle 2 Sekunden nachgeladen, die Seite selbst lädt erst am Ende neu). Danach automatisch:

- **Unsere Liste:** wird die neue aktuelle EK/VK-Liste des Herstellers.
- **Herstellerliste:** der **Jahresabgleich** startet sofort, danach direkt die Prüfseite.

Bricht ein Import ab oder schlägt fehl, geht die Liste zurück in den Entwurf und kann korrigiert werden.

## 6. Jahresabgleich prüfen und abschließen

Der Abgleich nimmt **unsere aktuelle Liste** (Vorjahr) und die **neue Herstellerliste** und rechnet für jeden
unserer Artikel:

1. **Zuordnung** zur Herstellerliste: exakt → normalisiert (ohne Leerzeichen, Bindestriche, Punkte) → ohne führende
   Nullen → ohne unser Kürzel → früher bestätigte Zuordnung. Unscharfe Treffer werden **nie** automatisch übernommen.
2. **EK neu** = Herstellerpreis (bzw. UVP − Händlerrabatt, bei Fremdwährung × Kurs, auf Cent gerundet).
3. **VK neu** = Kalkulation (siehe Reihenfolge in Abschnitt 4), danach **Gegenrechnung**. Weicht sie ab: Fehler,
   der alte Preis bleibt.

Artikel, die nur in der Herstellerliste stehen, werden ignoriert (sie gehören nicht zu unserem Sortiment).

### Status je Artikel

| Status | Bedeutung |
|---|---|
| in Ordnung | keine Auffälligkeit, nichts zu tun |
| Preisänderung | mindestens ein Prüfgrund (unten), muss bestätigt werden |
| Zuordnung unklar | möglicher Treffer, bitte Kandidat oder „kein Treffer“ wählen |
| fehlt beim Hersteller | nicht in der Herstellerliste, alter EK/VK bleibt |
| nicht in Teilliste | bei Teillisten: unverändert, nichts zu tun |
| Fehler | Berechnung nicht möglich (z. B. kein Preis, Kurs fehlt, Gegenrechnung abweichend), alter Preis bleibt |

### Prüfgründe

| Grund | Bedeutung | Was das Tool vorschlägt |
|---|---|---|
| EK-Änderung über Prüfschwelle | EK ändert sich um mindestens die Schwelle des Herstellers (EK-Änderung in % auf eine Nachkommastelle gerundet) | neuer EK und VK |
| VK-Änderung passt nicht zur EK-Änderung | Vorjahr war anders kalkuliert | neuer VK |
| alter VK passt nicht zur Kalkulation (**Sonderpreis**) | kalkulierter VK wäre niedriger als der alte, obwohl der EK nicht fällt | **alter VK bleibt** vorgeschlagen; „zurücknehmen“ setzt den kalkulierten |
| **Preis vom Vorjahr fehlt (EK 0,01)** | EK 0,01 in unserer Liste = kein Preis eingespielt oder Abverkauf | alter VK vorgeschlagen, kalkulierter VK im Hinweis; keine EK-Änderung in % |
| **EK unplausibel** | neuer EK ist mehr als 5 × oder weniger als 1/5 des alten EK, oder ohne Vorjahres-EK 1 Mio. € und mehr (falsche Spalte, EAN, Tippfehler) | **Fehler, alter EK/VK bleibt**; der Hinweis nennt Wert und Zeile der Herstellerliste. Nie in der Sammelbestätigung. Ist der Preis echt: Datei prüfen/korrigieren und neu einspielen |
| **VK unplausibel** | alter VK ist mehr als 20 × der neue EK (Tipp- oder Importfehler) | alter VK wird **nie** übernommen, kalkulierter VK |
| VK neu liegt unter EK neu | Kalkulation ergibt Verlust | prüfen |
| Preis ist 0 | | prüfen |
| kein EK / kein VK im Vorjahr | | neuer Preis |
| Kalkulation nicht automatisch nachrechenbar | Regel mit Formel/Staffel, keine Gegenrechnung möglich | prüfen |

### Prüfen

- Oben **„Offene anzeigen“**, Filter nach Status und Prüfgrund, Suche (auch mit Kürzel, z. B. `NL984`).
- **Bestätigen** je Zeile, optional mit **VK von Hand** (nicht unter EK).
- **Alle auf einmal bestätigen** (oben in der Fortschrittskarte, gilt für den aktuellen Filter): Häkchen
  „durchgesehen“ setzen, dann klicken. Nimmt nie unklare Zuordnungen oder Fehler mit; fehlende Artikel werden mit
  „alter Preis bleibt“ bestätigt. Der Knopf erscheint nur, wenn es etwas gesammelt zu bestätigen gibt.
- **Zuordnung unklar:** Kandidat wählen oder „kein Treffer – alten EK/VK behalten“. Die Entscheidung wird gespeichert
  und in künftigen Abgleichen wiederverwendet.
- **Einzelne Artikel anders kalkulieren** (aufklappbar, öffnet sich beim Anhaken): Artikel anhaken → Faktor
  (z. B. 2,8) oder Regel → gilt dauerhaft.
- **Zurücknehmen** macht eine Bestätigung rückgängig.
- **KI prüfen lassen** (wenn aktiv): schlägt für fehlende/unklare Artikel mögliche umbenannte Herstellerartikel vor.

Jede Zeile zeigt aufklappbar den Rechenweg (EK, Regel, jeder Schritt, Gegenrechnung).

### Abschließen

Sind alle Positionen geprüft: optional **„gültig ab“** eintragen → **Abschließen**. Das Tool

1. speichert das Ergebnis als **neue aktuelle Liste** („<Name> – Stand TT.MM.JJJJ“). Artikel, die während des
   Abgleichs über „Neue Artikel“ aufgenommen wurden, werden mit übernommen.
2. lädt die **neue Preisliste als Excel** herunter.

Danach zusätzlich verfügbar: **Preisänderungen für Kunden** (nur Artikel mit geändertem VK: alt → neu, Änderung %,
gültig ab). Vor dem Abschluss gibt es den **Entwurf-Export** (deutlich als ENTWURF gekennzeichnet).

**Excel „Neue Preisliste“** (Blätter Zusammenfassung, Neue Preisliste, Zu prüfen): Artikelnummer mit Kürzel,
Herstellerpreis mit Währung (in der endgültigen Liste nur bei UVP-Listen oder Fremdwährung, sonst ist er gleich dem
EK neu), EK alt/neu/Δ%, VK alt/neu/Δ%, Faktor VK/EK, Marge %, Währung und eine leere Spalte
**Kennzeichnung** zum Ausfüllen. Status, Prüfhinweise und Entscheidung stehen nur im **Entwurf-Export**. Regel, Rechenweg, Gegenrechnung und wer wann geprüft hat stehen nicht
in der Excel-Ausgabe, sondern in der App (Prüfseite, „Rechenweg“ je Zeile, Protokoll).

- **Marge** = (VK − EK) / VK × 100. Leer, wenn der EK fehlt oder 0,01 ist.
- **EK Δ%** und **VK Δ%** stehen immer da, bei „alter Preis behalten“ als 0 %. Leer nur ohne Vergleichswert
  (Vorjahres-EK 0,01 bzw. kein alter VK).
- Der **Rechenweg** auf der Prüfseite nennt die Zeile der Herstellerliste, aus der der Preis stammt.
- Der **Faktor VK/EK** ist das tatsächliche Verhältnis der endgültigen Preise, auf **eine Nachkommastelle** gerundet
  (2,8). Durch die VK-Rundung kann er leicht vom eingestellten Faktor abweichen; bei „alter Preis bleibt“ und
  „VK von Hand“ zeigt er das Verhältnis dieser Preise (z. B. 3,1).

## 7. Neue Artikel unterm Jahr

Menü **Neue Artikel** → Zeilen einfügen (z. B. aus Excel kopiert), Tab- oder Semikolon-getrennt:
`Artikelnummer mit Kürzel [; Bezeichnung [; EK]]`, höchstens 2000 Zeilen.

- Hersteller wird am **Kürzel** erkannt (`NL984-9020` → Nordic Lights). Mehrdeutige Kürzel werden nicht geraten.
- **EK:** aus der Zeile, sonst aus der neuesten Herstellerliste (mit Rabatt/Kurs wie im Abgleich).
- **VK:** Standardregel bzw. Ausnahme des Artikels, mit Gegenrechnung.
- Nicht aufgenommen werden: doppelt eingefügte, schon vorhandene, VK unter EK, Preis 0, kein Kürzel, keine
  aktuelle Liste.

Erst erscheint eine **Bestätigungsliste**; nach Häkchen und „Aufnehmen“ landen die Artikel in der aktuellen
EK/VK-Liste des Herstellers.

## 8. Preislisten ansehen und exportieren

Menü **Preislisten**: alle Listen mit Art (Unsere Liste / Herstellerliste), Hersteller, Status, Artikelzahl,
Meldungen. Die neueste „Unsere Liste“ je Hersteller ist die aktuelle.

- Liste öffnen: Artikel mit Preisen, Filter nach Status, Suche (auch mit Kürzel), Meldungen des Imports.
- **„Als Excel herunterladen“** (auf der Liste oder Download-Symbol in der Übersicht): die Liste im aktuellen Stand,
  inklusive später aufgenommener Artikel. Spalten: Artikelnummer (mit Kürzel), Original-Nr., Hersteller,
  Bezeichnung, Kategorie, Einheit, ggf. Staffel, EK / VK / UVP (nur vorhandene), Marge %, Kalk, Währung, Status.
  Status zusätzlich: „Preis fehlt (EK 0,01)“, „VK unplausibel (über 20 × EK)“. Blatt „Info“ mit Quelle, Stand,
  gültig ab.
- **Löschen** (Papierkorb, Bestätigung mit Häkchen): löscht Artikel, Kalkulationen, Vergleiche und Abgleiche, die
  auf der Liste aufbauen.

Alle Excel-Exporte schreiben Texte als Text (Schutz gegen Formel-Einschleusung) und Beträge als exakte Zahlen.

## 9. Regeln, Kalkulationen, Vergleiche

Für Sonderfälle; im normalen Jahresablauf nicht nötig.

**Regeln** (Menü Regeln): geordnete Rechenschritte auf einen Startpreis (EK, Listenpreis oder UVP):
Rabatt %, Aufschlag % (jeweils mit Basis: Startpreis, Zwischenpreis oder Ergebnis eines früheren Schritts),
Faktor, Fixbetrag, Staffelpreis für Menge, Mindestmenge, Runden auf Schrittweite, Runden auf Endung, Formel
(`+ - * /`, Klammern, `min`, `max`, Variablen `start`, `current`, `quantity`, `transport`, `discount`, `s1`, `s2` …).
Rundung kaufmännisch/mathematisch/auf/ab, 0–6 Stellen, **nach jedem Schritt** oder **nur am Ende**.
Jede Änderung erzeugt eine neue **Version**, alte Versionen bleiben unverändert (alte Ergebnisse nachvollziehbar).
„Testen“ rechnet einen Beispielpreis mit Rechenweg. Referenz: 100,00 − 15 % = 85,00; + 4 % = 88,40.

**Kalkulation** (Liste → Kalkulieren): wendet eine Regel auf alle Artikel einer Liste an, mit Rechenweg je Artikel
und Excel-Export.

**Vergleich** (Menü Vergleiche): zwei beliebige Listen gegenüberstellen (Listenpreis, EK, UVP oder kalkulierter
Preis). Status: unverändert, erhöht, gesenkt, neu, entfallen, geändert (Bezeichnung/Kategorie/Einheit), nicht
eindeutig, Fehler. Filter nach Status, Hersteller, Kategorie, Preisbereich. Unklare Zuordnungen bestätigen oder
ablehnen; Excel-Export mit den Blättern Zusammenfassung, Alle Artikel, Preisänderungen, Neue Artikel,
Entfallene Artikel, Unklare Zuordnungen und Fehler.

## 10. KI-Funktionen

Die KI (lokales Modell über Ollama auf demselben Server, keine Cloud) ist optional. Ist sie aus, sind die
KI-Knöpfe und KI-Hinweise ausgeblendet und alles andere funktioniert. Status: Übersicht → „System“ (Administratoren),
Seitenleiste „KI aktiv“ (nur sichtbar, wenn die KI läuft).

| Funktion | Wo | Ergebnis |
|---|---|---|
| Spaltenvorschlag | Import → Spalten anpassen | Vorauswahl nur für Spalten, die sonst nicht erkannt wurden |
| Zuordnung im Vergleich | Vergleich → KI | Kandidaten mit Begründung, nie automatisch übernommen |
| Prüfung im Abgleich | Abgleich → KI prüfen lassen | Hinweis „möglicher Treffer“, übernehmen oder ablehnen |
| Regelvorschlag | Regeln → aus Text | Vorschlag im Regel-Editor, wird erst nach Speichern gültig |

Die KI rechnet nie und bekommt nur kleine Ausschnitte (Kopfzeile + 5 Zeilen bzw. ein Artikel mit Kandidaten).
KI-Aufgaben laufen als Hintergrundjob (Menü **Jobs**, abbrechbar). Auf dem Server kann eine Anfrage bis zu einer
Minute dauern.

## 11. Modul Datenblatt erstellen

Startseite → **Datenblatt erstellen**. Die Übersicht zeigt oben eine **Suche** (Titel oder Artikelnummer, gilt für die
eigenen und die freigegebenen Datenblätter), darunter „Meine Datenblätter“ (mit erstem Produktbild und Zahl der Artikel)
und „Freigegebene Datenblätter“. Je Zeile: Vorschau/PDF, Kopieren, Löschen (Symbole rechts). Neu anlegen über
**„Neues Datenblatt“** oben rechts: im Fenster entweder **aus dem Hersteller-PDF** (Hauptweg, siehe unten) oder **leer
beginnen** (Titel und Serie). Wer noch kein Datenblatt hat, sieht beide Wege direkt auf der Seite.
Es öffnet sich der **Editor**: links die Eingabe, rechts das **Live-Blatt** im Druckformat A4. Jede Änderung wird
nach einer kurzen Pause automatisch gespeichert („Gespeichert hh:mm:ss“ oben), das Blatt rechts aktualisiert sich
sofort. Vorschau und Druck verwenden dieselbe Vorlage – was rechts steht, wird gedruckt.

**Kopf- und Fußzeile sind fest** und sehen immer gleich aus (blauer Balken mit Titel und Serie, Logo und
Firmendaten). Änderbar sind nur Titel, Untertitel und die Version in der Fußzeile.

**Bausteine** dazwischen (jeweils eine Karte, aufklappbar):

| Baustein | Inhalt |
|---|---|
| Einleitung | **Beschreibungstext** oben links (Blocksatz, Absätze mit Leerzeile), **Eigenschaften** „Name: Wert“ (vorbelegt wie in den Braun-&-Braun-Datenblättern: Spannungsbereich, Wasserdicht, Montage, Zulassungen, Gehäuse, Abmessungen; weitere z. B. Lichtleistung, Leuchtbild; leere werden nicht gedruckt; Werte dürfen mehrzeilig sein, z. B. „12V: …“ / „24V: …“ untereinander), getrennt davon die **Aufzählung** (Punkte unter dem Text, z. B. „5 Jahre Garantie“), bis zu 2 Produktbilder rechts. In der Live-Vorschau zeigt ein Platzhalter, wo der Text hinkommt (wird nicht gedruckt). |
| Spezifikationen | weitere Zeilen Merkmal/Wert (mehrzeilig) zusätzlich zu den Eigenschaften, Überschrift automatisch aus der Kopfzeile, optional mit **farbigem Zusatz** (z. B. „Tricolour“ in gelb/klar/blau wie beim Spartan), **Zulassungslogos automatisch** aus dem Feld „Zulassungen“, bis zu 2 Bilder rechts (z. B. Maßzeichnungen). Steht sie direkt nach der Einleitung, bilden beide den **Kopfbereich wie im Standard**: links Text, Aufzählung, Spezifikation untereinander, rechts alle Bilder über die ganze Höhe. |
| Anwendungsbilder | 2 Bilder nebeneinander (gleiche Höhe zugeschnitten) oder 1 Bild über die ganze Breite |
| **Tabelle** (beliebig oft) | Überschrift fett + Zusatz normal („**BESTELLINFORMATIONEN** - SERIE 12+ STANDARD VERSION“), Gruppenbild **links neben** der Tabelle (Gecko; mehrere Gruppenbilder in einer Tabelle: im Zeilenmenü (⋯) „Gruppenbild ab dieser Zeile“ wählen und ein Bild setzen – es steht links neben dieser und den folgenden Zeilen bis zur nächsten Zeile mit eigenem Gruppenbild, das Gruppenbild der Tabelle gilt für die Zeilen davor; wird eine Gruppe auf zwei Seiten geteilt, steht ihr Bild auf beiden) oder **über** der Tabelle (Leuchtbalken), Bilder je Zeile klein (Artikelliste) oder groß (Zubehör), bis zu 3 frei benennbare Zusatzspalten (z. B. Länge, Zulassung, Brutto VK), Zeilen mit Bild, Artikelnr., Farbpunkt (auch **mehrfarbig** als Tortendiagramm, z. B. gelb/blau/klar), Beschreibung, Werten. Zeilen auch **aus Excel einfügen** (Artikelnr. ⇥ Beschreibung ⇥ Zusatzspalten; Farbe aus dem letzten Farbwort der Beschreibung). |
| **Zubehör** | eine Tabelle mit Überschrift „Zubehör“ und großen Zeilenbildern |
| **Bild** (beliebig oft) | ein Bild über die volle Breite, Höhe klein/mittel/groß (30/50/80 mm), z. B. Seitenansicht unter der Spezifikation |

Neue Tabellen, Zubehör und Bilder: Knöpfe unter den Bausteinen, oder im Menü (⋯) eines Bausteins „… darunter“ –
dann steht der neue Baustein direkt unter diesem.

**Artikeltabelle** im Editor: eine Tabelle mit Spaltenköpfen (Bild, Artikelnr., Farbe, Beschreibung, Zusatzspalten).
Zusatzspalten über der Tabelle benennen (leeres Feld = keine weitere Spalte). **Enter** springt in die gleiche Spalte
der nächsten Zeile, in der letzten Zeile entsteht eine neue; **Pfeil hoch/runter** wechselt die Zeile. Im Zeilenmenü
(⋯): Zeile darunter einfügen, duplizieren, Gruppenbild ab dieser Zeile, löschen. Viele Spalten: die Tabelle scrollt
waagrecht.

**Freigeben (Marketing und Admin):** Ein neues Datenblatt ist ein **Entwurf** und nur für seinen Ersteller sichtbar –
und für Marketing und Admin, die dafür unter „Alle Datenblätter“ die Entwürfe aller Benutzer sehen. Marketing oder Admin
klicken in dieser Liste, oben im Editor oder in der Vorschau auf **„Freigeben“**: Dann steht das Blatt unter
„Freigegebene Datenblätter“ für **alle** Benutzer (Datenblatt | Benutzer | Geändert). Benutzer können nicht freigeben.
Freigegebene Blätter anderer kann man ansehen, drucken/als PDF speichern und als eigenen Entwurf kopieren, aber nicht
ändern; Bearbeiten und Löschen bleiben beim Ersteller und beim Admin, „Freigabe zurücknehmen“ bei Marketing und Admin.
Änderungen nach der Freigabe sind sofort in der gemeinsamen Liste sichtbar. Die Suche über der gemeinsamen Liste findet
Titel und Artikelnummern (Leerzeichen, Bindestriche, Groß-/Kleinschreibung egal) – so sieht man schnell, ob es zu einem
Artikel schon ein Datenblatt gibt.

**Aus Hersteller-Datenblatt erstellen:** In der Datenblatt-Übersicht das PDF des Herstellers hochladen, den
Hersteller wählen (oder „automatisch erkennen“: der Herstellername bzw. ein Alias wird im PDF gesucht, unter den
eigenen Herstellern; der Prüfbericht nennt den erkannten Hersteller) → „Datenblatt erstellen“. Der Hersteller bestimmt
Kürzel, Preislisten-Abgleich und das Wörterbuch. Ein Hintergrundjob füllt den Baukasten, danach öffnet sich der
Editor mit einem Prüfbericht oben (mit × ausblendbar). Übernommen werden:

| Aus dem PDF | In den Baukasten |
|---|---|
| erste Überschrift auf Seite 1 (sonst Titel aus den PDF-Eigenschaften); Klammerzusatz oder „ - …“ | Titel und Serie. Steht dort nur der Serienname (z. B. „Scorpius GO 410“), wird die **Produktart aus dem Text** erkannt (Arbeitsscheinwerfer, Rundumleuchte, Leuchtbalken, Blitzmodul …, auch englisch) und Titel – „LED“ davor, wenn LED oder Lumen im Blatt steht –, der Serienname wird „Serie …“ |
| Abschnitt „Anwendung/Beschreibung/Produkt…“ (sonst erster längerer Text) | Beschreibungstext, gekürzt auf 2–3 Sätze; läuft die **lokale KI**, formuliert sie ihn kurz auf Deutsch (Zahlen, die nicht im PDF stehen, werden verworfen) |
| Aufzählungspunkte (•), Abschnitt „Hauptmerkmale/Features“ | Eigenschaften ohne Namen |
| **Englische Blätter** | Begriffe und Werte auf B&B-Deutsch (Montagearten, Deutsch Stecker, Farben, Zulassung „ECE-R10“) und B&B-Schreibweise („10-30V“, „2.200lm“, „IP67, IP69k“). Modelltabelle (PART NO./VOLTAGE/MOUNT) wird Bestelltabelle; „Part No.“ bei Blättern für ein Modell. Blitzende Beacons werden „Blitzleuchten“, rotierende „Rundumleuchten“. Der Beschreibungstext bleibt englisch, außer die lokale KI ist aktiv |
| „Technische Daten/Spezifikationen“ | **B&B-Begriffe in B&B-Reihenfolge**: Spannungsbereich, Lichtleistung, Wasserdicht (aus Schutzart/IP), Montage, Zulassungen, Gehäuse (aus Material), Abmessungen, Leuchtbild. Garantie wird Aufzählungspunkt („2 Jahre Garantie“) |
| übrige Technische Daten | bis zu 3 weitere Zeilen (wichtige zuerst), der Rest steht im Prüfbericht. Mehrere Spalten (z. B. 12 V / 24 V) werden untereinander geschrieben, mehrzeilige Werte zusammengehalten. Zwei Datentabellen nebeneinander (z. B. Nordic Lights) werden getrennt gelesen; Fußzeilen mit Adresse, Web, Telefon werden ignoriert |
| „Artikelnummern/Bestellinformationen“ oder jeder Abschnitt mit Artikelliste (Überschrift wird Gruppenname), auch als Matrix (Ausführung × Spannung); weitere Spalten wie Länge, Zulassung, Montage, Abmessungen werden Zusatzspalten. „Tricolour/Dual Colour“ im Serienname wird farbiger Zusatz der Spezifikation | je Gruppe eine Tabelle „Bestellinformationen – Gruppe“, eine Zeile je Nummer mit Beschreibung (Artikelart vorne, z. B. „LED-Lichtsignalgeber, rot, 12 V DC“) und Farbpunkt; „Zubehör“ als Zubehörtabelle. Mit Hersteller: Kürzel davor und Abgleich mit der aktuellen Preisliste (Anzahl im Bericht) |
| Artikelnummern im Fließtext einer Datenzeile („Wide Flood (36-48 V): 988-208B, …“) | eigene Tabelle „Bestellinformationen“, Beschreibung „LED Arbeitsscheinwerfer Scorpius GO 410, Wide Flood (36-48 V)“ |
| eingebettete Bilder (nur die tatsächlich auf der Seite gezeichneten) | **oben rechts nur das Produkt selbst**: freigestellte Produktfotos der ersten Seite, sonst Studioaufnahmen vor einfarbigem Hintergrund. Maßzeichnungen (auch freigestellte Strichzeichnungen, weißer Rand wird abgeschnitten) → Spezifikation; Leuchtreichweite/Lichtverteilung (farbige Fläche auf weißem Papier) → eigener Bild-Baustein unter den Bestellinformationen; weitere Studioaufnahmen werden nicht unten wiederholt; Fotos → Anwendungsbilder (je höchstens 2; Logos und Kleinteile werden übersprungen) |

Das PDF muss echten Text enthalten (keine Scans), bis 25 MB; gegen Bearbeiten geschützte PDFs gehen. Das
Herstellerblatt wird nach dem Einlesen gelöscht. Lichtverteilungsdiagramme und Steckerfotos werden bewusst nicht übernommen. Wie B&B Herstellerangaben übersetzt und platziert, steht in `docs/DATENBLATT-REGELN.md`. Alles ist ein Vorschlag: bitte im Editor prüfen und korrigieren.

**Design-Vorlagen (nur Admin):** Datenblätter → „Design-Vorlagen“. Eure fertigen Datenblätter als PDF hochladen (auch
mehrere auf einmal). Gespeichert wird nur das Original-PDF (über „PDF“ ansehen, löschen); es wird **kein** Datenblatt
daraus nachgebaut. Im Hintergrund liest das Tool je PDF ab: wo welche Bilder sitzen und wie groß sie sind (Position aus
dem PDF; Kopf- und Fußzeile mit Logo zählen nicht), den Beschreibungstext, die Aufzählung, die Zeilennamen der
Spezifikation und die Artikelbeschreibungen. Die Produktart kommt aus dem Titel und kann je Vorlage geändert werden
(mehrere mit Komma). Oben zeigt die Seite je Produktart, wie das Tool daraus neue Blätter baut.

Beim Import aus einem Herstellerblatt gelten die Vorlagen derselben Produktart (verwandte zählen mit: „Arbeitsscheinwerfer“
nimmt „Scheinwerfer“), sonst alle gemeinsam. Übernommen werden: Anzahl der Produktbilder und Zeichnungen, Bildgrößen
(Mittelwert eurer Blätter), Aufteilung Text/Bilder (aus der Position der Bilder), ob Anwendungsbilder gezeigt werden,
Namen und Reihenfolge der Eigenschaften und Spezifikationszeilen, der Garantie-Punkt als **ausgeblendeter** Vorschlag.
Die lokale KI bekommt eure Texte und Artikelbeschreibungen als Vorbild und formuliert Beschreibung und
Artikelbeschreibungen in eurem Stil; Zahlen müssen dabei gleich bleiben, sonst bleibt der Originalwortlaut. Werte,
Artikel und Bilder der Vorlagen werden nie übernommen. Der Prüfbericht nennt, nach wie vielen Vorlagen gebaut wurde.
Früher (mit der alten Funktion) nachgebaute Vorlagen stehen unten auf der Seite und werden nicht mehr verwendet.
Unser eigenes Logo wird beim Einlesen nie als Produktbild genommen.

**Wörterbuch (nur Admin):** Datenblätter → „Wörterbuch“. Einträge „Begriff im Herstellerblatt → unser Begriff“, je
Eintrag eine Art: **Merkmal** (Zeilenname, z. B. „Actual lumen“ → „Lichtleistung“; Standardzeile oder eigene
Spezifikationszeile), **Wert** (Ausdruck in Werten, Aufzählungen und Artikelbeschreibungen, z. B. „Mag 70“ →
„Magnetmontage“), **Produktart** (z. B. „work light“ → „Arbeitsscheinwerfer“, Einzahl). „Gilt für“: alle Hersteller
oder einer (Name; gleich benannte Hersteller verschiedener Benutzer teilen sich die Einträge). Reihenfolge: Eintrag des
Herstellers vor „alle Hersteller“ vor den eingebauten Regeln (unten auf der Seite aufklappbar). Gleicher Begriff
nochmal speichern = überschreiben. Groß-/Kleinschreibung egal. Wirkt beim nächsten Import, bestehende Datenblätter
bleiben unverändert. Bei englischen Blättern listet der Prüfbericht Begriffe ohne Übersetzung; der Admin sieht daneben
„ins Wörterbuch“ (öffnet das Formular vorausgefüllt mit Art, Begriff und Hersteller).

**Bedienung:**

- **Verschieben:** am Griff (⋮⋮) ziehen – Bausteine, Eigenschaften, Spezifikationszeilen und Tabellenzeilen.
  Alternativ Griff anklicken und Pfeiltasten ↑/↓.
- **Menü (⋯) am Baustein:** „Auf neuer Seite beginnen“, nach oben/unten, Artikeltabelle/Zubehör/Bild darunter einfügen,
  Tabelle duplizieren, Baustein entfernen. „neue Seite“ steht danach in der Kurzinfo des Bausteins.
- **Rückgängig:** Knopf oben (oder Strg+Z außerhalb eines Textfelds) nimmt die letzte Änderung zurück, auch mehrmals
  (bis 30 Schritte, gilt im geöffneten Browser-Tab; Tippen wird zu Schritten von einigen Sekunden zusammengefasst). Nach
  dem Entfernen von Bausteinen oder Zeilen erscheint unten ein Hinweis mit „Rückgängig“ – deshalb gibt es keine
  Sicherheitsfrage mehr. In Textfeldern gilt das normale Rückgängig des Browsers.
- **Prüfliste** über den Bausteinen: zeigt, was vor dem Druck noch fehlt (Titel, Beschreibungstext, Produktbild,
  technische Daten, leere Tabellen, Zeilen ohne Artikelnummer oder Beschreibung, doppelte Artikelnummern, Bild-Baustein
  ohne Bild, Version). Klick auf einen Punkt öffnet die Stelle. Ist alles da: „Alles Wichtige ist ausgefüllt“.
- **Vorschau:** Seitenwechsel mit ‹ › („Seite 1 von 2“), Zoom „Breite“ (passt sich an) oder 50/75/100 %; „?“ zeigt die
  Maus-Funktionen der Vorschau.
- **Ausblenden:** Auge am Baustein oder an einer Eigenschaft – bleibt gespeichert, wird aber nicht gedruckt.
- **Produktbilder oben rechts verschieben:** in der Live-Vorschau mit gedrückter Maustaste an die gewünschte
  Stelle ziehen (gilt auch für den Druck). Doppelklick setzt das Bild an seinen Platz zurück.
- **Bildgröße ändern:** in der Live-Vorschau über ein Bild fahren, am blauen Griff an der Ecke unten rechts ziehen
  (nach rechts/unten größer, nach links/oben kleiner, 30–300 %, die Prozentzahl wird beim Ziehen angezeigt). Gilt für
  Produktbilder, Bilder bei der Spezifikation, Anwendungsbilder, Bild-Bausteine und Gruppenbilder der Tabellen (nicht
  für die kleinen Zeilenbilder). Doppelklick auf den Griff = Originalgröße; Doppelklick auf ein Produktbild setzt Platz
  und Größe zurück. „Bilder zurücksetzen“ über der Vorschau (erscheint, sobald ein Bild verschoben oder skaliert ist) setzt alle Bilder zurück. Die Seitenaufteilung rechnet mit
  der Größe; wird eine Seite zu voll, erscheint wie gewohnt der rote Hinweis.
- **Aufteilung Text / Bilder** (Baustein Einleitung, neben „Produktbilder“): „Standard“ (Text 92 mm), „Größere Bilder“
  (Text 78 mm, Bildspalte breiter) oder „Mehr Text“ (Text 106 mm).
- **Bilder:** Platz anklicken oder eine Datei hineinziehen. Gefüllte Bilder per Ziehen zwischen beliebigen Plätzen
  **tauschen**, × entfernt. JPG, PNG, GIF, WebP bis 10 MB; geprüft wird der Inhalt, nicht die Endung.
- **Klick ins Live-Blatt** öffnet die passende Eingabe links.
- **Seitenaufteilung** automatisch in der Reihenfolge der Bausteine. Tabellen bis 6 Zeilen werden nie geteilt, längere
  nur mit mindestens 3 Zeilen je Seite („(Fortsetzung)“). Eine zu volle Seite wird **rot umrandet** mit Hinweis, ebenso ein zu langer Titel.
- **Drucken / PDF:** Knopf oben rechts → Druckansicht → „Drucken / als PDF speichern“ → im Druckdialog
  **Als PDF speichern**, **A4**, Ränder **Keine**, **Hintergrundgrafiken** an.

**Zulassungslogos:** „ECE-R65 Klasse II, ECE-R10, CISPR 25“ ergibt ECE-R65 (blau, „KLASSE 2“ in Orange), ECE-R10
(schwarz) und CISPR 25 (gold), in der eingegebenen Reihenfolge. Klasse wird erkannt als „Klasse I/II“, „Kl. 1/2“,
„Class“; mehrere R65-Klassen ergeben ein Logo mit der höchsten. Andere Zeichen (E-Prüfzeichen, SAE) werden nicht
erkannt. Die Eigenschaft „Zulassung“ kann ausgeblendet werden, die Logos bleiben.

**Weiteres:** Der PDF-Import läuft als Hintergrundjob; die Warteseite zeigt den Fortschritt und öffnet das Datenblatt
automatisch. „Kopieren“ in der Übersicht legt eine Kopie mit allen Bildern an (Vorlage für die nächste Serie).
Löschen mit Bestätigung entfernt auch die Bilder. Datenblätter aus der früheren Schritt-Eingabe werden beim Öffnen
automatisch in Bausteine übernommen. **Schrift:** Myriad Pro, falls auf dem Rechner installiert, sonst die mitgelieferte
**Source Sans 3** (Adobe, gleiche Schriftfamilie, freie Lizenz SIL OFL 1.1) – damit sieht das Blatt auf jedem Rechner
gleich aus und die Seitenaufteilung stimmt.

## 12. Modul Vertriebswissen

Startseite → **Vertriebswissen**. Gemeinsames Wissen, das sonst nur in Köpfen steckt: „Nordic Lights hat eine
Mindestbestellmenge von 36 Stück, kleinere Mengen über Riedfeld“, „Leuchtbalken über 1,80 m mehr kalkulieren“,
„dieser Scheinwerfer braucht unbedingt den Montageadapter“.

**Startseite – drei Spalten, volle Bildschirmbreite:** links **Hersteller**, rechts **Artikelgruppen**, in der Mitte
die **Infos** (Umschalter „Infos | Karte“).

- **Listen:** Firmengruppen stehen links zusammen (Mutter, darunter eingerückt die Töchter, farbiger Strich wie die
  Blase auf der Karte). Zahl = Einträge, oranger Punkt = etwas ist zu prüfen, grau = nicht gefolgt. Jede Liste hat ein
  eigenes Filterfeld; Enter wählt den ersten Treffer.
- **Artikelgruppen beim Hersteller zuordnen** (welche Gruppen er führt, z. B. Redtronic → Leuchtbalken,
  Rundumleuchten): im Infofenster des Herstellers unter „Artikelgruppen“ wählen und „Hinzufügen“, oder mit Hersteller
  und Gruppe gewählt auf „… hinzufügen“. × an der Gruppe löst die Zuordnung. Von der Gruppe aus
  geht es genauso („Hersteller“). Jede Zuordnung steht mit Name und Zeit im Verlauf; auf der Karte erscheint eine
  Artikel-Linie.
- **Nur Hersteller wählen** (z. B. Redtronic): in der Mitte **alle Redtronic-Infos** (zugeordnete Artikelgruppen,
  Bezug, Angaben, Artikel, Einträge). Die Listen markieren nur die eigene Auswahl – nichts bleibt dauerhaft eingefärbt.
- **Nur Artikelgruppe wählen:** **alle Infos zur Gruppe** (zugeordnete Hersteller, Artikelvergleich, Einträge).
- **Erst Hersteller, dann Artikelgruppe wählen** (Klick in der rechten Liste oder auf die Gruppe im Infofenster): oben
  in der Mitte erscheint die **Verbindung als Grafik** – „Redtronic ── führt ── Leuchtbalken“ mit Anzahl Artikel und
  Einträge; ist die Gruppe nicht zugeordnet, ist die Linie gestrichelt („nicht zugeordnet“) mit Knopf „Leuchtbalken
  zu Redtronic hinzufügen“. Auf der Karte sind dann nur diese beiden und ihre Linie hervorgehoben. Darunter **alle
  Infos zu beiden**: Redtronic-Artikel in der Gruppe mit Platz im Vergleich (aufklappbar die anderen Hersteller),
  Pflicht-Zubehör zwischen beiden, **Einträge zu beiden** (dort direkt neu eintragen – der Eintrag gehört dann zu
  beiden), **„Gilt für alle Leuchtbalken“** und **„Gilt für alles von Redtronic“** (Bezugsregel, Angaben, allgemeine
  Einträge). Klick auf einen der beiden Kästen oder „Alles zu …“ wechselt zu einem allein.
- Umgekehrt geht genauso: Gruppe zuerst wählen, links werden die passenden Hersteller hervorgehoben.
- Nochmal auf den gewählten Eintrag klicken = abwählen; × in der Mitte hebt alles auf (Überblick).
- **Überblick** (nichts gewählt): „Bitte prüfen“ (zuerst „Du bist zuständig“), „Zuletzt geändert“, „Ohne Zuständigen“.
- **Einzelner Hersteller/Gruppe:** Firmengruppe, **Bezug** (Bezugsregel als zwei Zeilen „Ab 36 Stück oder Lagerware →
  bei Nordic Lights“ / „Unter 36 Stück und keine Lagerware → bei Riedfeld“, beim Händler die Gegenrichtung),
  **Angaben** (darunter „Fehlt: …“), **Artikel**, **Einträge nach Art**. Überall direkt **neu eintragen** (Strg+Enter),
  **„stimmt noch“** und **„stimmt nicht mehr“** ohne Seitenwechsel. Ändern, Löschen, Bezugsregel, Firmengruppe und
  Angaben über **„Steckbrief bearbeiten“**.
- **Karte** (Reiter): Hersteller (Kreise), Artikelgruppen (Quadrate), **Bezugsregel** (blauer Pfeil zum Händler),
  **Pflicht-Zubehör** (orange gestrichelt), **Artikel** (grün erste Wahl … rot gestrichelt abraten),
  **Firmengruppen** (Blasen). „Anzeigen“ blendet Linienarten ein/aus. Klick wählt wie in den Listen, Doppelklick öffnet
  den Steckbrief.
- **Links weitergeben:** `/wissen?t=…` (ein Thema) bzw. `/wissen?f=…&g=…` (Hersteller × Gruppe) öffnen die Ansicht direkt.
- **Handy/schmal:** Listen oben, darunter Infos/Karte.

Am Kartenhintergrund ziehen = verschieben, Mausrad oder +/− = zoomen, Kreise lassen sich ziehen, „Alles zeigen“ passt
die Ansicht an.

**Bezugsregel (Beispiel Nordic Lights / Riedfeld):** Eine Bedingung, wann beim Hersteller und wann woanders bestellt
wird. Festlegen im Steckbrief im Kasten „Bezugsregel“ (im Infofenster „Festlegen“) oder auf der Karte über „Verbinden“ –
beides ist derselbe Satz zum Ausfüllen:

> Bei **Nordic Lights** bestellen ab **[36]** Stück **[✓] oder wenn Lagerware**. Sonst bestellen bei **[Riedfeld ▾]**.
> Bemerkung (optional), z. B. „dort andere Kalkulation“.

Mindestmenge, Lagerware oder beides (mindestens eins). Danach:

- **Steckbrief Nordic Lights:** Kasten „Bezugsregel“ mit Frage „Ab 36 Stück oder Lagerware?“ und zwei Ästen –
  grün „ja → Bei Nordic Lights bestellen“, blau „nein · unter 36 Stück und keine Lagerware → Bei Riedfeld bestellen →“
  (Klick öffnet Riedfeld). „Regel ändern“ öffnet den Satz, dort auch „Regel entfernen“ (die Mindestmenge bleibt).
- **Karte:** blauer Pfeil Nordic Lights → Riedfeld mit „unter 36 Stk / keine Lagerware“; Infofenster von Nordic
  Lights unter „Bezug“ die beiden Zeilen, Klick auf Riedfeld öffnet dessen Infos.
- **Umgekehrt bei Riedfeld:** im Infofenster unter „Bezug“ und oben im Steckbrief „Für Nordic Lights: unter 36 Stück
  und keine Lagerware → hier bestellen“.
- **Hinweise bei der Arbeit** (Preisliste, Jahresabgleich, Datenblatt): „Ab 36 Stück oder Lagerware → bei Nordic
  Lights bestellen, sonst (unter 36 Stück und keine Lagerware) → bei Riedfeld“.

**Verbinden auf der Karte:** Knopf **„Verbinden“**, dann das erste Thema antippen, dann das zweite. Ein Fenster fragt,
welche Verbindung (mit „⇄ umdrehen“ für die Richtung):

- **Bezugsregel** (nur bei Herstellern): derselbe Satz wie oben, das zweite Thema ist der Händler.
- **„A braucht [1] × B (Pflicht-Zubehör)“** – Pflicht-Zubehör mit Stückzahl.
- **„Firmengruppe: B ist Tochterfirma von A“** (nur zwischen Herstellern) – siehe Firmengruppen.
- **„Hinweis zu beiden“** – ein Eintrag, der beiden zugeordnet ist.

„Verbinden“ speichert (mit Name und Zeit wie im Steckbrief), die Karte zeigt sofort die neue Linie. Bezug und
Pflicht-Zubehör erscheinen als **Pfeil mit Beschriftung** („unter 36 Stk / keine Lagerware“, „2 ×“). Ändern oder
löschen: Bezugsregel im Kasten „Bezugsregel“, Pflicht-Zubehör bei den Angaben (Bleistift, leer speichern entfernt).

**Firmengruppen (Beispiel EccoESG mit LED Autolamps und Vision Alert):** Hersteller können eine
**Muttergesellschaft** haben. Festlegen im Steckbrief im Kasten **„Firmengruppe“** (nur Hersteller): „Gehört zu
(Muttergesellschaft)“ wählen – speichert sofort – oder bei der Mutter „Tochterfirma hinzufügen“; „Lösen“ nimmt eine
Tochter wieder heraus. Alternativ auf der Karte über „Verbinden“. Eine Firma hat höchstens eine Mutter, Kreise
(A gehört zu B gehört zu A) werden abgelehnt; mehrstufig (Enkel) geht, die Gruppe zählt dann zur obersten Mutter.
Danach:

- **Karte:** alle Firmen einer Gruppe liegen in einer **farbigen Blase** mit Namen („EccoESG-Gruppe“), jede Gruppe in
  eigener Farbe. Töchter werden zur Mutter gezogen. Zieht man eine Firma weg, **verformt sich die Blase mit** und
  umschließt weiter alle Mitglieder. **Fremde Firmen liegen nie in der Blase:** sie macht einen Bogen um sie herum
  (Verbindungsstück auf der freien, kürzeren Seite). Ist rundherum kein Platz, zerfällt sie in mehrere Teile in derselben
  Farbe. Schon beim Aufbau der Karte werden fremde Firmen aus Gruppen herausgeschoben. „Anzeigen → Firmengruppen“ blendet die Blasen aus. Im Infofenster
  stehen alle Firmen der Gruppe unter „Firmengruppe“; in der Liste links stehen sie zusammen.
- **Steckbrief:** oben die Mitglieder der Gruppe als Chips (Mutter markiert, Klick öffnet).
- **Suche:** „ecco“ findet auch alle Töchter.

**Themen:** links die **Hersteller** und **Artikelgruppen**. Die Herstellerliste ist **gemeinsam für alle**: Jeder
Hersteller aus den Preislisten aller Benutzer steht automatisch einmal darin (gleicher Name oder Alias = derselbe
Hersteller, Schreibweise wie „Nordic-Lights“/„nordic lights“ egal). Im Steckbrief steht dann „In deiner Preisliste:
Nordic Lights (NL)“ mit Link. Weitere Hersteller und Artikelgruppen links über „+ Hersteller oder Artikelgruppe“
anlegen, mit **anderen Schreibweisen** (z. B. Lichtbalken, Warnbalken), damit sie im Text erkannt werden.

**Folgen:** Schalter „Folge ich“ im Infofenster und im Steckbrief (dort links auch neben jedem Thema). Standard: allem folgen. Was man ausschaltet, verschwindet aus der eigenen
Übersicht und Suche; für die anderen bleibt alles da. Beispiel: Michi verkauft nur Fahrzeugtechnik und schaltet alle
anderen Hersteller aus.

**Eintragen:** oben in das Feld einfach so schreiben, wie man denkt, z. B. „nordic moq 36 stk“. Noch beim Tippen zeigt
das Tool (ohne KI, mit festen Regeln):

- die **Art**: Bezugsweg / Bedingung (Mindestmenge, „bestellen über“, Lagerartikel), Kalkulation (Aufschlag, Faktor,
  „mehr kalkulieren“, %), Pflicht-Zubehör („braucht“, „unbedingt“, „nur mit“), Lieferzeit / Kontakt, sonst Hinweis.
  Anklicken ändert sie.
- **Gehört zu**: alle Hersteller und Gruppen, deren Name oder Schreibweise im Text vorkommt; mit × entfernen, mit
  „+ zuordnen“ ergänzen. Wird nichts erkannt, gehört der Eintrag zum gerade geöffneten Steckbrief; auf der Übersicht
  muss man dann selbst zuordnen.
- **Wird gespeichert als**: einheitliche Schreibweise – Herstellername wie im Steckbrief, Abkürzungen ausgeschrieben
  (stk → Stück, moq → Mindestbestellmenge, mind. → mindestens, zb → z. B.), bekannte Artikelgruppen und häufige
  Substantive (Lieferzeit, Wochen, Kalkulation, Aufschlag …) groß, Zahl und Einheit getrennt (1,80m → 1,80 m), großer Satzanfang, Punkt am Ende. Zahlen bleiben unverändert. Das Original
  bleibt im Verlauf („So eingetippt“).

- **Als Angabe übernehmen**: Erkennt das Tool eine Mindestbestellmenge („moq 36 stk“, „Mindestbestellmenge … = 36
  Stück“) oder Lieferzeit („Lieferzeit 6 Wochen“, „2-3 Wo.“), bietet es ein Häkchen an, den Wert zusätzlich als feste
  Angabe beim ersten zugeordneten Thema zu speichern. Nie automatisch: Einschränkungen wie „bei den meisten Artikeln“
  gingen im Feld verloren – dann nur den Eintrag speichern.

Enter speichert. „nur für mich“ = privater Eintrag, den nur der Ersteller sieht.

**Steckbrief** eines Herstellers oder einer Gruppe:

- **Zuständig** (oben rechts): eine Person je Hersteller/Gruppe. Sie sieht Meldungen und überfällige Einträge dieses
  Themas auf der Übersicht zuerst („Du bist zuständig“). Themen ohne Zuständigen stehen auf der Übersicht.
- **Firmengruppe** (nur Hersteller, ganz oben): siehe oben.
- **Bezugsregel** (nur Hersteller): siehe oben.
- **Angaben** als **feste Felder**: Lieferzeit, Ansprechpartner (nur Hersteller) und
  **Pflicht-Zubehör** (Artikelgruppe oder Hersteller, Stück je Artikel, Bemerkung; mehrere möglich). Bleistift
  ändert, leer speichern entfernt, unverändert speichern bestätigt. Unter jedem Feld stehen Name und Zeitpunkt der
  letzten Änderung; nach 6 Monaten steht dort „bitte prüfen“. Daneben „weitere Angabe“ für freie Kurzinfos
  (z. B. Mindestbestellwert, Frachtfrei ab).
- **Artikelvergleich** (nur bei Artikelgruppen, z. B. „Blue-Spot-Scheinwerfer“): Artikel verschiedener Hersteller
  von Hand eintragen („+ Artikel“: Hersteller, Artikelnummer, Bezeichnung, Punkte 1–5 je Kriterium, „Warum?“).
  Vorbelegte Kriterien: Helligkeit, Qualität, Preis, Lieferbarkeit; unter „Kriterien“ umbenennen oder ändern
  (höchstens 6; Umbenennen behält die Punkte nach Position). Rang nach Punkteschnitt (nur bewertete Kriterien
  zählen), daraus die Stufe: ab 4,25 **erste Wahl**, ab 3,5 **gut**, ab 2,5 **nur wenn nötig**, darunter **abraten**;
  ohne Punkte „noch nicht bewertet“ (am Ende). Bleistift ändert, dort auch löschen; Name und Zeit stehen dabei, jede
  Änderung im Verlauf. Beim **Hersteller** steht „In Artikelgruppen“ mit seinem Platz („Platz 1 von 3 · erste Wahl“).
  Der Hinweiskasten bei der Arbeit nennt die erste Wahl der Gruppe bzw. wo ein Hersteller erste Wahl ist.
- **Einträge** nach Art gruppiert (Farbe je Art). Jeder Eintrag zeigt Ersteller und Zeitpunkt, nach Änderungen
  „geändert von … am …“, und die anderen zugeordneten Themen als Links. **Bearbeiten** dürfen alle (Text, Art,
  Zuordnung); privat schalten nur der Ersteller. **Verlauf** zeigt jede Änderung mit Name, Zeitpunkt und dem Text
  davor. Löschen mit Bestätigung; im Verlauf bleibt vermerkt, wer wann gelöscht hat.
- **Verknüpfungen**: Bild mit allen Herstellern und Gruppen, die über gemeinsame Einträge oder feste Felder
  (Bezug über, Pflicht-Zubehör) verbunden sind; „Genannt bei“ im Kopf zeigt, wer auf dieses Thema verweist (Linie nach
  der wichtigsten Art: Pflicht-Zubehör gestrichelt orange, Bezugsweg, Kalkulation). Klick öffnet den Steckbrief.
  Auf dem Handy als Liste.
- **Verlauf** unten: die letzten Änderungen an diesem Thema.

**Kalkulationshinweise** sind Information und frei änderbar; sie rechnen nicht in der Preisliste mit.

**Bitte prüfen:** Prüffrist je Art – Lieferzeit/Kontakt 3 Monate, Bezugsweg und Kalkulation 6 Monate, Pflicht-Zubehör
und Hinweise 12 Monate (was sich schnell ändert, kommt früher wieder). Danach ist der Eintrag orange markiert und
steht auf der Übersicht unter „Bitte prüfen“. Jeder kann bei einem Eintrag **„Stimmt nicht mehr“** melden (optional
mit Bemerkung): Der Eintrag zeigt die Meldung mit Name und Zeit und steht ganz oben bei „Bitte prüfen“, beim
Zuständigen unter „Du bist zuständig“. „stimmt noch“ bestätigt (mit Name und Datum), Bearbeiten korrigiert; beides
erledigt die Meldung.

**Hinweise bei der Arbeit:** Was beim Anbieten zählt, erscheint dort, wo man arbeitet – als Kasten „Vertriebswissen“
mit wenigen Zeilen (höchstens 6; nur Mindestmenge mit Bezugsweg, Pflicht-Zubehör, Lieferzeit und Einträge der Arten
Pflicht-Zubehör, Bezugsweg, Kalkulation):

- **Preisliste → Hersteller** und **Jahresabgleich** dieses Herstellers (Zuordnung über Name/Alias wie oben),
- **Datenblatt-Editor**, wenn Titel, Serie oder Artikelbeschreibungen einen Hersteller oder eine Gruppe nennen.

Klick führt zum Eintrag. Themen, denen man nicht folgt, erscheinen nicht. Überfällige Einträge tragen „bitte prüfen“.

**Suche:** Feld oben rechts oder **Strg+K**. Findet Hersteller, Gruppen (auch über andere Schreibweisen), Angaben und
Einträge (auch den ursprünglich eingetippten Text), nur bei Themen, denen man folgt. **Jedes Suchwort zählt einzeln**
(Reihenfolge egal, alle müssen vorkommen: „nordic moq“ findet „Nordic Lights … Mindestbestellmenge“); Groß-/
Kleinschreibung, Umlaute, Leer- und Bindestriche sind egal. **Synonyme** werden mitgesucht. Pfeiltasten + Enter
öffnen den Treffer; Enter ohne Auswahl öffnet die ausführliche Trefferliste („Auch gesucht nach: …“).

**Suchbegriffe** (links „Suchbegriffe und Synonyme“): Gruppen gleichbedeutender Wörter, z. B. „Mindestbestellmenge,
MOQ, Mindestmenge, Mindestabnahme“ (drei allgemeine Gruppen sind vorbelegt, alle änderbar). Jeder darf ändern, Name
und Zeit stehen dabei; leer speichern löscht. Daneben **Suchen ohne Treffer**: Was in der ausführlichen Suche nichts
gefunden hat, mit Anzahl und wer zuletzt gesucht hat (beim Tippen wird nichts protokolliert). Von dort: als Eintrag
erfassen (+) oder als erledigt abhaken. Wird ein Wort als Synonym ergänzt, verschwindet es aus der Liste.

**Übersicht** ohne gewähltes Thema: „Zuletzt geändert“ bei allem, dem man folgt, und „Bitte prüfen“.

## 13. Verwaltung (Administratoren)

- **Benutzer:** anlegen (Rolle Benutzer, Marketing oder Administrator, Passwort ≥ 12 Zeichen), Rolle ändern (der
  Betroffene wird abgemeldet; die eigene Admin-Rolle kann man sich nicht nehmen), deaktivieren/aktivieren
  (beendet Sitzungen), Passwort zurücksetzen (hebt Sperre auf). Das eigene Konto kann nicht deaktiviert werden.
  Benutzer werden nicht gelöscht, nur deaktiviert.
- **Protokoll:** alle Aktionen mit Zeit, Benutzer, IP und Details (Importe, Abgleiche, Prüfungen, Exporte,
  Anmeldungen, Fehlversuche, Löschungen).
- Administratoren sehen in allen Übersichten eine Spalte „Benutzer“ und können fremde Daten bearbeiten. Übernimmt
  ein Administrator den Abgleich eines Benutzers, gehört die neue Liste weiterhin dem Benutzer.

## 14. Häufige Fragen und Fehlerbilder

| Frage / Bild | Antwort |
|---|---|
| Spalte **Kalk** ist leer | Kalk zeigt nur einen Faktor, der in unserer Liste beim Artikel stand. Leer = Standardregel des Herstellers. |
| VK höher als EK × Faktor, obwohl keine Kalk | „Sonderpreis“: der alte VK war höher und wird nie still gesenkt. In der Prüfung „zurücknehmen“ setzt den kalkulierten. |
| Marge 100 % | kommt nicht mehr vor bei EK 0,01 (Marge leer). Sonst: VK im Verhältnis zum EK sehr hoch, siehe Status „VK unplausibel“. |
| „Mehrdeutiger Wert 1.234“ | Spalte hat keine eindeutigen Dezimalzahlen. Unter „Spalten anpassen“ das Trennzeichen der Spalte festlegen. |
| „Keiner unserer Artikel gefunden“ | falscher Hersteller oder Kürzel-Einstellung (Kürzel abschneiden?) prüfen |
| Liste in falscher Währung importiert | Liste löschen und mit richtiger Währung neu einspielen; das Tool blockiert den Abgleich vorher |
| Excel zeigt alte Werte | Excel-Datei neu herunterladen; Downloads werden nicht nachträglich geändert |
| Änderung am Server nicht sichtbar | Update ausführen (Teil B), danach im Browser Strg+F5 |
| Datenblatt-Seite rot umrandet | zu viel Inhalt: Text kürzen, weniger Zeilen oder Bilder, oder einen Baustein mit „neue Seite“ beginnen |

---

# Teil B – Betrieb

Ausführlich in [`docs/betrieb.md`](betrieb.md). Kurzfassung:

**Aufbau:** Hetzner-Server (Ubuntu 24.04), nginx (HTTPS) → `127.0.0.1:8010` → Docker-Container `app`
(FastAPI, SQLite) + Container `ollama` (KI, internes Netz ohne Internet). Installationsort `/root/apps/preisliste`,
Daten in `deploy/data/` (Datenbank `preisliste.sqlite3`, `uploads/` mit Excel-Dateien und `uploads/datenblatt/`
mit Datenblatt-Bildern, `backups/`).

**Update** (nach jeder Änderung auf GitHub):

```
cd ~/apps/preisliste && git pull && sudo bash deploy/install.sh
```

Datenbank-Migrationen laufen beim Start automatisch. Danach im Browser Strg+F5.

**Befehle** (im Ordner `deploy/`, jeweils mit `docker compose exec app python -m backend.cli …`):

| Befehl | Wirkung |
|---|---|
| `create-admin <name>` | Administrator anlegen (Passwort wird abgefragt) |
| `reset-password <name>` | Passwort setzen, Sperre aufheben, Sitzungen beenden |
| `backup [anzahl]` | Sicherung sofort, behält die letzten N (Standard 14) |
| `clear-data --ja` | Hersteller, Listen, Artikel, Kalkulationen, Vergleiche, Excel-Uploads löschen. Benutzer, Regeln, Datenblätter, Protokoll bleiben. Vorher automatische Sicherung. |
| `clear-data --ja --regeln` | zusätzlich alle Regeln |
| `clear-data --ja --alles` | zusätzlich alle Regeln und alle Nicht-Admin-Benutzer samt deren Datenblättern |
| `reset-data --ja` | **alles** löschen (App vorher stoppen, siehe betrieb.md), danach `create-admin` |

**Sicherung:** täglich 02:17 Uhr, die letzten 14 bleiben in `deploy/data/backups/`. Inhalt: Datenbank (konsistente
Kopie mit Integritätsprüfung) und der Ordner `uploads/` (Excel-Dateien und Datenblatt-Bilder). Die Sicherungen
liegen auf demselben Server – regelmäßig woandershin kopieren. Wiederherstellen: siehe betrieb.md.

**Logs:** `docker compose logs --tail 100 app`. **Status:** `docker compose ps`. **Health:** `/health`.

---

# Teil C – Technik

## Architektur

| Schicht | Ort | Inhalt |
|---|---|---|
| Web | `backend/api/` | FastAPI-Routen, je Bereich eine Datei (`routes_*.py`), Jinja2-Vorlagen in `frontend/templates/` |
| Dienste | `backend/services/` | Geschäftslogik: Import, Smart-Import, Abgleich starten, neue Artikel, Hersteller, Regeln, Datenblätter, Dashboard, Sichtbarkeit (`access.py`), Löschen, Sicherung, Protokoll |
| Excel | `backend/excel/` | sicheres Lesen (`reader.py`), Spaltenerkennung (`columns.py`), Zahlen (`numbers.py`), Import (`importer.py`), Export (`export.py`) |
| Rechnen | `backend/calculations/` | Regelengine (`engine.py`), unabhängige Gegenrechnung (`verify.py`), Formelparser ohne `eval` (`formula.py`) |
| Abgleich/Vergleich | `backend/comparison/` | Jahresabgleich (`update.py`), Vergleich (`service.py`) |
| Zuordnung | `backend/matching/cascade.py` | Matching-Kaskade, unscharfe Kandidaten (rapidfuzz) |
| Jobs | `backend/jobs/` | ein Worker-Thread im App-Prozess, Fortschritt im Speicher, Abbruch über DB-Flag |
| KI | `backend/ai/` | Ollama / lokaler OpenAI-kompatibler Server / Mock, JSON-Schema, pydantic-Validierung |
| Datenbank | `backend/database/`, `backend/models/entities.py` | SQLite (WAL), SQLAlchemy 2, Alembic-Migrationen `0001`–`0012` |
| Frontend | `frontend/static/` | `style.css` (Hell/Dunkel über Tokens), `app.js` (Komfort, Drag & Drop), `datasheet.css/js` (A4-Blatt, Prüfung auf Überlauf), `datasheet_editor.js` (Editor: Autosave, Sortieren, Bilder) |

Ein Prozess, ein Worker (`--workers 1`), weil SQLite und die Jobs im Prozess laufen.

## Datenmodell (Kurzfassung)

| Tabelle | Inhalt |
|---|---|
| `users`, `sessions` | Konten (Argon2id), Sitzungen (nur SHA-256 des Cookies gespeichert, CSRF-Token) |
| `manufacturers` | Hersteller je Besitzer: Kürzel, Aliase, EK/UVP, Rabatt, Währung, Kurs, Schwelle, Standardregel |
| `rules`, `rule_versions` | Regeln; Versionen per DB-Trigger unveränderlich (kein UPDATE/DELETE) |
| `rule_exceptions` | Ausnahmen je Hersteller: ARTIKEL / PREFIX / SERIE → Regel |
| `price_lists`, `articles`, `article_prices`, `import_messages` | Listen (Art UNSERE/HERSTELLER, Status ENTWURF → WARTESCHLANGE → IMPORTIERT), Artikel (Nummer, normalisiert, Kalk), Preise (EK/LISTE/UVP, Staffel, Währung), Meldungen |
| `price_updates`, `price_update_items` | Jahresabgleich mit Momentaufnahme der Einstellungen; je Artikel EK/VK alt/neu, Status, Prüfgründe, Entscheidung NEU/ALT/MANUELL, Rechenweg, Gegenrechnung, KI-Hinweis |
| `calculation_runs`, `calculation_results` | Kalkulationen mit Rechenweg |
| `comparisons`, `comparison_items`, `match_decisions`, `ai_match_suggestions` | Vergleiche, gespeicherte Zuordnungsentscheidungen (auch im Abgleich genutzt), KI-Vorschläge |
| `jobs` | Hintergrundjobs (IMPORT, AI_COLUMNS, AI_MATCH, AI_UPDATE_MATCH, AI_RULE) |
| `datasheets` | Datenblätter: Titel, Inhalt als JSON (Kopf, Eigenschaften, Spezifikation, Fußzeile und die Liste der Bausteine mit Reihenfolge; Bilder nur als Dateiname) |
| `kb_assortment` | Vertriebswissen: welche Artikelgruppen ein Hersteller führt (Hersteller, Gruppe, wer, wann) |
| `kb_topics`, `kb_facts`, `kb_entries`, `kb_unfollow`, `kb_changes`, `kb_synonyms`, `kb_search_misses`, `kb_products` | Vertriebswissen: Artikelvergleich (Gruppe, Hersteller, Artikel, Punkte je Kriterium, Begründung; Kriterien je Gruppe in `kb_topics.criteria`), gemeinsame Themen (Hersteller, Artikelgruppen; Name, Schlüssel, Muttergesellschaft `parent_id`, andere Schreibweisen, Zuständiger), Angaben im Steckbrief (feste Felder mit Menge/Verweis oder frei), Synonymgruppen, Suchen ohne Treffer, Einträge (Art, Text, eingetippter Text, privat, Themen-IDs, Ersteller/geändert/geprüft mit Benutzer und Zeit), wem man nicht folgt, Verlauf jeder Änderung |
| `audit_log`, `settings` | Protokoll, Einstellungen |

Beträge liegen als exakter Dezimaltext (`DecimalText`), nie als float.

## Sicherheit

- Anmeldung: Argon2id, Konto-Sperre, IP-Begrenzung, gleiche Laufzeit bei unbekanntem Benutzer.
- Cookies `httponly`, `secure`, `samesite=strict`; CSRF-Token in jedem Formular; Herkunftsprüfung bei POST.
- Header: strenge Content-Security-Policy (nur eigene Skripte/Styles, keine Inline-Skripte), `X-Frame-Options: DENY`,
  `nosniff`, `no-store`.
- Sichtbarkeit zentral in `services/access.py`; fremde Objekte liefern 404.
- Excel: Größen- und Zip-Prüfung vor dem Öffnen, Makros/`.xls` abgelehnt, `defusedxml` Pflicht, Formeln nie
  ausgeführt. Exporte gegen Formel-Einschleusung geschützt.
- Datenblatt-Bilder: Inhaltsprüfung (Magic Bytes), kein SVG, zufällige Dateinamen, Auslieferung nur angemeldet.
- KI nur an lokale Hosts (`localhost`, `ollama`); Antworten werden validiert, nie ausgeführt.
- Keine Telemetrie (FastAPI-Telemetrie aus, `OTEL_*` im Image deaktiviert). Container: read-only, ohne Capabilities.

## Konfiguration

Umgebungsvariablen mit Präfix `PREIS_` (`backend/config.py`), Auswahl:

| Variable | Standard | Bedeutung |
|---|---|---|
| `PREIS_DATA_DIR` | `data/` | Datenbank, Uploads, Sicherungen |
| `PREIS_COOKIE_SECURE` | `true` | im lokalen Test ohne HTTPS `false` |
| `PREIS_MAX_UPLOAD_MB` | 25 | Upload-Grenze |
| `PREIS_SESSION_IDLE_MINUTES` / `_MAX_HOURS` | 480 / 72 | Sitzungsdauer |
| `PREIS_LOGIN_MAX_FAILURES` / `_LOCKOUT_MINUTES` | 5 / 15 | Konto-Sperre |
| `PREIS_MIN_PASSWORD_LENGTH` | 12 | |
| `PREIS_PAGE_SIZE` | 50 | Zeilen je Seite |
| `PREIS_AI_PROVIDER` | `ollama` | `ollama`, `local`, `none` |
| `PREIS_OLLAMA_URL` / `PREIS_AI_MODEL` | `http://ollama:11434` / `llama3.2:3b` | |
| `PREIS_AI_TIMEOUT_SECONDS` / `PREIS_AI_RETRIES` | 90 / 2 | |

Spaltenüberschriften für die Erkennung: `config/header_synonyms.yaml` (neue Schreibweisen dort ergänzen).

## Entwicklung und Tests

```
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest                      # alle Tests außer Belastungstest
.venv/bin/pytest -m slow -s           # Belastungstest 50.000 Zeilen
PREIS_COOKIE_SECURE=false .venv/bin/python -m backend.cli create-admin admin
PREIS_COOKIE_SECURE=false .venv/bin/uvicorn backend.main:app --port 8010
```

Wichtige Testdateien: `test_e2e_szenarien.py` (kompletter Ablauf mit realistischen Listen, u. a. Nordic Lights),
`test_price_update.py` (Abgleich), `test_engine.py` (Rechnen, Rundung), `test_numbers.py` (Zahlenformate),
`test_user_isolation.py` (Sichtbarkeit), `test_datasheets.py`, `test_list_export.py`, `test_regressionen.py`.
Testdaten für den Ablauf: `beispiel-daten/`.

Datenbankänderungen nur über eine neue Alembic-Migration in `backend/database/migrations/versions/`.

Weitere Dokumente: Anforderungen `docs/anforderungen-v2.md`, Architektur `docs/phase1-architektur.md`,
Lizenzen/Netzwerk der Abhängigkeiten `docs/abhaengigkeiten.md`.

---

# Glossar

| Begriff | Bedeutung |
|---|---|
| **Unsere Liste** | unsere EK/VK-Liste eines Herstellers; die neueste ist die **aktuelle Liste** |
| **Herstellerliste** | neue Preisliste des Herstellers (EK oder UVP) |
| **Jahresabgleich** | unsere aktuelle Liste + Herstellerliste → neue EK/VK-Liste, mit Prüfung |
| **Teilliste** | Herstellerliste mit nur einzelnen Serien (Preiserhöhung); fehlende Artikel bleiben unverändert |
| **Kürzel** | Firmenkürzel des Herstellers vor der Artikelnummer (NL, RA, ST …) |
| **Faktor** | VK = EK × Faktor (Standardkalkulation des Herstellers) |
| **Kalk** | Faktor je Artikel aus unserer Liste, überschreibt den Standard |
| **Gegenrechnung** | unabhängige zweite Berechnung jedes VK; Abweichung = Fehler |
| **Sonderpreis** | alter VK höher als kalkuliert; wird nie still gesenkt |
| **EK 0,01** | Platzhalter: Preis fehlt oder Abverkauf; immer zur Prüfung |
| **Marge** | (VK − EK) / VK × 100 |
| **Job** | Aufgabe im Hintergrund (Import, KI) mit Fortschritt und Abbruch |
