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
  - [12. Verwaltung (Administratoren)](#12-verwaltung-administratoren)
  - [13. Häufige Fragen und Fehlerbilder](#13-häufige-fragen-und-fehlerbilder)
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
  - *Administrator*: zusätzlich alles von allen Benutzern sehen und bearbeiten, Benutzer verwalten, Protokoll.

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
- **Kennzahlen:** Hersteller, Artikel in den aktuellen Listen, offene Prüfungen, Abgleiche im Jahr, neue Artikel
  der letzten 30 Tage.
- **Herstellerkacheln:** aktuelle Liste, Stand, Ø EK- und VK-Änderung des letzten Abgleichs, Status.

## 4. Hersteller einrichten

Menü **Hersteller** → Name und Kürzel eingeben → „Anlegen“, danach die Einstellungen öffnen.

| Feld | Bedeutung |
|---|---|
| **Name** | pro Benutzer eindeutig |
| **Kürzel** | 1–10 Zeichen A–Z/0–9, pro Benutzer eindeutig. Steht in Anzeige und Export direkt vor der Artikelnummer (Kürzel `NL` + `984-9020` = `NL984-9020`). Gespeichert wird die Nummer **ohne** Kürzel. |
| **Aliase** | weitere Schreibweisen des Namens (mit `;` getrennt), helfen bei der Erkennung |
| **Faktor** | Standardkalkulation: **VK = EK × Faktor**, z. B. 2,8. Legt automatisch die Regel „<Hersteller> Standard“ an. Jede Änderung erzeugt eine neue Regelversion. |
| **VK-Rundung** | keine (Cent) · auf 10 Cent · auf 10 Cent aufrunden · auf volle Euro · auf ,90 / ,95 / ,99 (Endungen runden immer **auf**, die Marge sinkt also nie) |
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

Der Import läuft als **Hintergrundjob** (Seite mit Fortschritt, abbrechbar). Danach automatisch:

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
| prüfen | mindestens ein Prüfgrund (unten), muss bestätigt werden |
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
| **VK unplausibel** | alter VK ist mehr als 20 × der neue EK (Tipp- oder Importfehler) | alter VK wird **nie** übernommen, kalkulierter VK |
| VK neu liegt unter EK neu | Kalkulation ergibt Verlust | prüfen |
| Preis ist 0 | | prüfen |
| kein EK / kein VK im Vorjahr | | neuer Preis |
| Kalkulation nicht automatisch nachrechenbar | Regel mit Formel/Staffel, keine Gegenrechnung möglich | prüfen |

### Prüfen

- Oben **„Offene anzeigen“**, Filter nach Status und Prüfgrund, Suche (auch mit Kürzel, z. B. `NL984`).
- **Bestätigen** je Zeile, optional mit **VK von Hand** (nicht unter EK).
- **Alle bestätigen** (für den aktuellen Filter): nimmt nie unklare Zuordnungen oder Fehler mit.
- **Zuordnung unklar:** Kandidat wählen oder „kein Treffer – alten EK/VK behalten“. Die Entscheidung wird gespeichert
  und in künftigen Abgleichen wiederverwendet.
- **Anders kalkulieren:** Artikel anhaken → Faktor (z. B. 2,8) oder Regel → gilt dauerhaft.
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
Herstellerpreis, EK alt/neu/Δ%, VK alt/neu/Δ%, Faktor VK/EK, Marge %, Status, Prüfhinweise, Entscheidung, Regel,
Rechenweg, Gegenrechnung, geprüft von/am.

- **Marge** = (VK − EK) / VK × 100. Leer, wenn der EK fehlt oder 0,01 ist.
- **EK Δ%** ist leer, wenn der Vorjahres-EK 0,01 war.
- Der **Faktor** wird ohne angehängte Nullen geschrieben (2,8). Bei „VK von Hand“ bleibt er leer.

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
KI-Knöpfe ausgeblendet und alles andere funktioniert. Status: Übersicht → „System“, Seitenleiste „KI aktiv“.

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

Startseite → **Datenblatt erstellen** → Titel (Produktgruppe) und Untertitel (Serie) eingeben → „Neues Datenblatt“.
Es öffnet sich der **Editor**: links die Eingabe, rechts das **Live-Blatt** im Druckformat A4. Jede Änderung wird
nach einer kurzen Pause automatisch gespeichert („Gespeichert hh:mm:ss“ oben), das Blatt rechts aktualisiert sich
sofort. Vorschau und Druck verwenden dieselbe Vorlage – was rechts steht, wird gedruckt.

**Kopf- und Fußzeile sind fest** und sehen immer gleich aus (blauer Balken mit Titel und Serie, Logo und
Firmendaten). Änderbar sind nur Titel, Untertitel und die Version in der Fußzeile.

**Bausteine** dazwischen (jeweils eine Karte, aufklappbar):

| Baustein | Inhalt |
|---|---|
| Einleitung | **Beschreibungstext** oben links (Blocksatz, Absätze mit Leerzeile), darunter Aufzählung „**Name:** Wert“ (vorbelegt: Spannung, LED-Farbe, Anzahl LEDs, Schutzart, Zulassung, Montage, Garantie; Name leer lassen = nur der Text, z. B. „5 Jahre Garantie“), bis zu 2 Produktbilder rechts. In der Live-Vorschau zeigt ein Platzhalter, wo der Text hinkommt (wird nicht gedruckt). |
| Spezifikationen | Tabelle Merkmal/Wert (mehrzeilig), Überschrift automatisch aus der Kopfzeile, **Zulassungslogos automatisch** aus dem Feld „Zulassung“, bis zu 2 Bilder rechts (z. B. Maßzeichnungen). Steht sie direkt nach der Einleitung, bilden beide den **Kopfbereich wie im Standard**: links Text, Aufzählung, Spezifikation untereinander, rechts alle Bilder über die ganze Höhe. |
| Anwendungsbilder | 2 Bilder nebeneinander (gleiche Höhe zugeschnitten) oder 1 Bild über die ganze Breite |
| **Tabelle** (beliebig oft) | Überschrift fett + Zusatz normal („**BESTELLINFORMATIONEN** - SERIE 12+ STANDARD VERSION“), Gruppenbild **links neben** der Tabelle (Gecko) oder **über** der Tabelle (Leuchtbalken), Bilder je Zeile klein (Artikelliste) oder groß (Zubehör), bis zu 3 frei benennbare Zusatzspalten (z. B. Länge, Zulassung, Brutto VK), Zeilen mit Bild, Artikelnr., Farbpunkt, Beschreibung, Werten. Zeilen auch **aus Excel einfügen** (Artikelnr. ⇥ Beschreibung ⇥ Zusatzspalten; Farbe aus dem letzten Farbwort der Beschreibung). |
| **Zubehör** | eine Tabelle mit Überschrift „Zubehör“ und großen Zeilenbildern |
| **Bild** (beliebig oft) | ein Bild über die volle Breite, Höhe klein/mittel/groß (30/50/80 mm), z. B. Seitenansicht unter der Spezifikation |

Neue Tabellen, Zubehör und Bilder: Knöpfe unter den Bausteinen.

**Bedienung:**

- **Verschieben:** am Griff (⋮⋮) ziehen – Bausteine, Eigenschaften, Spezifikationszeilen und Tabellenzeilen.
  Alternativ Griff anklicken und Pfeiltasten ↑/↓.
- **Neue Seite:** Häkchen am Baustein – er beginnt auf einer neuen Seite.
- **Ausblenden:** Auge am Baustein oder an einer Eigenschaft – bleibt gespeichert, wird aber nicht gedruckt.
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

**Weiteres:** „Kopieren“ in der Übersicht legt eine Kopie mit allen Bildern an (Vorlage für die nächste Serie).
Löschen mit Bestätigung entfernt auch die Bilder. Datenblätter aus der früheren Schritt-Eingabe werden beim Öffnen
automatisch in Bausteine übernommen. **Schrift:** Myriad Pro, falls auf dem Rechner installiert, sonst die mitgelieferte
**Source Sans 3** (Adobe, gleiche Schriftfamilie, freie Lizenz SIL OFL 1.1) – damit sieht das Blatt auf jedem Rechner
gleich aus und die Seitenaufteilung stimmt.

## 12. Verwaltung (Administratoren)

- **Benutzer:** anlegen (Rolle Benutzer oder Administrator, Passwort ≥ 12 Zeichen), deaktivieren/aktivieren
  (beendet Sitzungen), Passwort zurücksetzen (hebt Sperre auf). Das eigene Konto kann nicht deaktiviert werden.
  Benutzer werden nicht gelöscht, nur deaktiviert.
- **Protokoll:** alle Aktionen mit Zeit, Benutzer, IP und Details (Importe, Abgleiche, Prüfungen, Exporte,
  Anmeldungen, Fehlversuche, Löschungen).
- Administratoren sehen in allen Übersichten eine Spalte „Benutzer“ und können fremde Daten bearbeiten. Übernimmt
  ein Administrator den Abgleich eines Benutzers, gehört die neue Liste weiterhin dem Benutzer.

## 13. Häufige Fragen und Fehlerbilder

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
