# Projekt: Offline-Preislisten- und Kalkulationssystem mit optionaler lokaler KI

## 1. Ziel

Entwickle eine vollständig lokal und offline nutzbare Anwendung zur Verarbeitung von Excel-Preislisten (.xlsx).

- Zielsystem: Windows 10/11, 8 bis 16 GB RAM, CPU ohne dedizierte GPU.
- Zielgröße: bis ca. 10.000 Artikel pro Liste. Belastungstest mit 50.000 Zeilen.
- Es dürfen keine Geschäftsdaten (Preislisten, Artikel, Einkaufspreise, Herstellerdaten) das lokale System verlassen.
- Keine Cloud-KI, keine externen APIs, keine Telemetrie.

## 2. Harte Grundregeln (haben Vorrang vor allem anderen)

1. **Die App muss ohne KI vollständig funktionieren.** KI ist ein optionaler Helfer für unklare Fälle, keine Voraussetzung.
2. **Die KI rechnet nie.** Alle Berechnungen erfolgen deterministisch in festem Programmcode.
3. **Die KI erzeugt keinen Code.** Sie liefert ausschließlich JSON nach festem Schema. Dieses wird validiert und von festen Funktionen verarbeitet. Kein `eval`, kein `exec`, keine KI-generierten Shell-Befehle.
4. **Geldbeträge ausschließlich mit `decimal.Decimal`**, nie mit float. Rundungsregel (Modus, Stellen, Zeitpunkt: pro Schritt oder nur am Ende) ist pro Regel konfigurierbar. Standard: kaufmännisch (ROUND_HALF_UP) auf 2 Stellen **nach jedem Rechenschritt** (Zwischenergebnisse werden gerundet und mit dem gerundeten Wert weitergerechnet). Jeder Zwischenwert wird im Rechenweg mit dem gerundeten Betrag gespeichert. Alternativ pro Regel "nur am Ende" wählbar.
5. **Die KI darf unsichere Zuordnungen nie automatisch übernehmen.** Unter einem konfigurierbaren Schwellwert muss der Benutzer bestätigen. Confidence-Werte kleiner Modelle sind nicht kalibriert und gelten nur als Sortierhilfe, nicht als Wahrscheinlichkeit.
6. **Keine Daten raten.** Bei Unklarheit: Status FEHLER, WARNUNG oder UNKLAR, sichtbar markiert. Nie stillschweigend falsche Daten erzeugen.
7. **Excel-Dateien sind nicht vertrauenswürdige Eingaben.** Keine Makros ausführen, keine Formeln als Code behandeln, keine Befehle aus Zellen übernehmen.
8. **Webserver nur an 127.0.0.1 binden**, nie an 0.0.0.0.

## 3. Verarbeitungs-Pipeline

```
Excel -> Parser (Python/pandas/openpyxl) -> normalisiertes Datenmodell (SQLite)
      -> Matching-Kaskade (exakt, normalisiert, fuzzy, erst dann KI)
      -> Regelengine (Decimal-Berechnung, versioniert)
      -> Ergebnis + Erklärung -> Excel-Export
```

Die KI bekommt nie ganze Excel-Dateien, nur kleine Ausschnitte (z. B. Kopfzeile plus 5 Beispielzeilen, oder ein einzelnes Artikelpaar mit Kandidaten).

### 3.1 Spaltenerkennung (Reihenfolge)

1. Header-Synonymliste (konfigurierbar, z. B. Art.-Nr., SKU, Artikelnummer, EK, UVP, Listenpreis, Preis netto).
2. Heuristik (Datentyp, Eindeutigkeit, Wertebereich).
3. KI nur als Fallback, mit Schema-Ausgabe. Ergebnis immer in der Vorschau vom Benutzer bestätigen.

Excel-Eigenheiten berücksichtigen: Kopfzeile nicht in Zeile 1, mehrere Kopfzeilen, verbundene Zellen, leere Zeilen, mehrere Tabellenblätter, Formelzellen (`data_only` liefert nur gecachte Werte; fehlt der Cache, als WARNUNG melden). Unterstützt wird .xlsx. Bei .xls oder .xlsm eine klare Fehlermeldung bzw. definierte Behandlung (Makros nie ausführen).

### 3.2 Artikelzuordnung (Matching-Kaskade)

1. Exakter Match auf (Hersteller, Artikelnummer).
2. Normalisierter Match (Groß/Kleinschreibung, Bindestriche, Leerzeichen, Punkte, führende Nullen nach definierter Regel).
3. Fuzzy-Match (z. B. `rapidfuzz`) über Artikelnummer und Bezeichnung. Liefert Kandidatenliste mit Score.
4. KI nur für den verbleibenden Rest, als **Hintergrundjob mit Fortschrittsanzeige, Abbruchmöglichkeit und Zeitlimit pro Anfrage**.
5. Alles unter dem Schwellwert landet in der Statusgruppe NICHT_EINDEUTIG und wird in der UI mit Kandidatenvorschlägen zur manuellen Bestätigung angeboten. Bestätigte Zuordnungen werden gespeichert und wiederverwendet.

Hintergrund: Bei 8.000 Artikeln würden schon 2 % KI-Fälle (160 Anfragen) auf CPU mit einem 3B-Modell Dutzende Minuten dauern. Deshalb muss die Kaskade zwingend vorgeschaltet sein.

## 4. Datenmodell (SQLite)

Mindestens: article_number, article_number_normalized, manufacturer, description, category, supplier_price, list_price, discount, transport_cost, quantity, currency, valid_from, source_file, source_sheet, source_row, calculated_price, previous_price, price_difference, price_difference_percent, status, rule_id, rule_version, calculation_trace (strukturiert, Einzelschritte), confidence, match_method.

Zusätzlich beachten: mehrere Preise pro Artikel (Staffeln, Währungen, Gültigkeit) müssen im Modell abbildbar und beim Vergleich eindeutig behandelt werden. Doppelte Artikelnummern innerhalb einer Liste werden als WARNUNG markiert und nicht stillschweigend überschrieben.

Weitere Tabellen: Hersteller, Regeln (versioniert, unveränderlich nach Speichern), Importhistorie, bestätigte Zuordnungen, Benutzerkonfiguration, Audit-Log (wer hat wann welche Regel geändert).

## 5. Regelengine

- Regeln liegen in der Datenbank bzw. Konfigurationsdateien, nie im Code.
- Jede Regel besteht aus geordneten Schritten. **Jeder Schritt definiert explizit seine Berechnungsbasis** (z. B. Listenpreis oder Zwischenpreis), um Mehrdeutigkeiten zu vermeiden.
- Schritttypen: Rabatt in Prozent, Aufschlag in Prozent, Fixbetrag, Staffelpreis, Mindestmenge, Rundung, individuelle Formel.
- Individuelle Formeln über einen sicheren Ausdrucksparser mit Whitelist (z. B. `simpleeval`), nie über `eval`.
- Regeln werden vom Administrator im Editor eingegeben. Die KI darf höchstens einen Regelvorschlag aus Freitext machen, der erst nach Bestätigung gespeichert wird.
- Regelversionierung: Jede Änderung erzeugt eine neue Version (v1, v2, v3). Jede Berechnung speichert die verwendete Regelversion, alte Ergebnisse bleiben nachvollziehbar.
- Nachvollziehbarkeit pro Position: Ausgangspreis, jeder Rechenschritt mit Zwischenergebnis, Endpreis, Regel und Version.

Referenzbeispiele für Tests: 100,00 - 15 % = 85,00; 85,00 + 4 % = 88,40 (Transport 3,40 bezogen auf den Preis nach Rabatt).

## 6. Vorjahresvergleich

Vergleich über Artikelnummer und Hersteller (optional weitere Identifikatoren). Status:
UNVERÄNDERT, PREIS_ERHÖHT, PREIS_GESENKT, NEUER_ARTIKEL, ENTFALLENER_ARTIKEL, ARTIKEL_GEÄNDERT, NICHT_EINDEUTIG.

Differenz absolut und in Prozent werden mit Decimal berechnet. Ergebnis-Zusammenfassung: Anzahl analysiert, unverändert, erhöht, gesenkt, neu, entfallen, nicht eindeutig.

## 7. KI-Schnittstelle

- Abstraktion `AIProvider` mit `OllamaProvider`, `LocalModelProvider`, `MockProvider`. Modell konfigurierbar (Standard z. B. `llama3.2:3b`, austauschbar gegen Qwen, Mistral u. a. ohne Änderung am Rest).
- Ollama Structured Outputs (JSON-Schema) verwenden. Antworten mit pydantic validieren. Ungültige Antworten: begrenzte Wiederholung, danach Status UNKLAR. Nie ungeprüft verarbeiten.
- Beim Start prüfen: Ollama erreichbar, Modell vorhanden. Wenn nicht: App läuft ohne KI weiter, mit klarem Hinweis.
- Beispielschemata: Spaltenerkennung (manufacturer, article_number_column, price_column, confidence) und Artikelzuordnung (old_article, new_article, match, confidence, reason).
- Der `MockProvider` wird für alle automatischen Tests verwendet, damit Tests ohne Modell laufen.

## 8. Benutzeroberfläche

Lokale Weboberfläche (FastAPI, Bindung an 127.0.0.1). Bereiche: Dashboard, Preislisten, Hersteller, Kalkulationsregeln, Vergleiche, Einstellungen.

- Preislisten: Import, Blattauswahl, erkannte Spalten und Hersteller anzeigen und bestätigen, Datenvorschau.
- Vergleich: alte und neue Liste, Hersteller wählen, Ergebnis-Zusammenfassung.
- Filter: alle, erhöht, gesenkt, unverändert, neu, entfallen, unklar, Hersteller, Kategorie, Preisbereich.
- **Serverseitige Paginierung und Filterung**, keine 8.000+ Zeilen auf einmal ans Frontend.
- Regel-Editor: Hersteller und Regeln anlegen, bearbeiten, löschen, mit Versionsanzeige.
- Statusanzeige: "OFFLINE", KI aktiv oder inaktiv.
- Fehler, Warnungen, Unklares deutlich getrennt sichtbar.

## 9. Export

Excel-Export mit Blättern: Zusammenfassung, Alle Artikel, Preisänderungen, Neue Artikel, Entfallene Artikel, Unklare Zuordnungen, Kalkulation (mit Rechenschritten), Fehler. Beim Schreiben Zelleninhalte gegen Formel-Injektion absichern (Werte, die mit `=`, `+`, `-`, `@` beginnen, als Text schreiben).

## 10. Deutsche Zahlenformate und Währungen

"1.234,56 €" muss als 1234.56 interpretiert werden. Unterstützt: EUR/€, USD, CHF. Unbekannte Währung führt zu FEHLER, keine stillschweigende Annahme. Währungsumrechnung ist nicht im MVP.

## 11. Tests

Automatische Tests (pytest) für: Rabatt, Aufschlag, Fixbetrag, Rundung (inkl. Randfälle wie x,xx5 und Fälle, in denen Rundung pro Schritt und Rundung am Ende unterschiedliche Ergebnisse liefern), Prozentänderung, Staffeln, Regelversionierung, Vergleichsstatus (neu, entfallen, doppelt, nicht eindeutig), Spaltenerkennung für unterschiedliche Layouts, Matching-Kaskade, deutsche Zahlenformate, fehlende und ungültige Werte, kaputte Excel-Dateien, JSON-Validierung inkl. ungültiger KI-Antworten (Mock), Sicherheit (Formelinjektion, Makrodateien), Belastungstest mit 50.000 Zeilen.

Wenn echte Beispiellisten (anonymisiert) im Ordner `tests/data/` liegen, sind diese zusätzlich zu synthetischen Daten als Testgrundlage zu verwenden.

## 12. Projektstruktur

```
price-ai/
  backend/ (api, models, services, calculations, excel, ai, matching, manufacturers, database)
  frontend/
  config/ (manufacturers, rules, header_synonyms)
  tests/ (inkl. data/)
  data/
  exports/
  docs/
  requirements.txt
  README.md
```

Anpassungen sind erlaubt, wenn sie begründet werden.

## 13. Installation (Windows)

- Ziel: einfacher Installer oder portable Distribution, identisch auf mehreren PCs installierbar.
- **Offline-Installationspaket** vorsehen, das Anwendung, Abhängigkeiten, Ollama-Installer und Modelldatei enthält (Modell-Download ist beim Erstsetup sonst ein Widerspruch zur Offline-Anforderung).
- Erkennung von Ollama und Modell, geführte Konfiguration.
- Abhängigkeiten auf Lizenz und Notwendigkeit prüfen, keine Pakete mit Telemetrie oder Netzwerkzugriff zur Laufzeit.

## 14. Ressourcen (8 GB RAM)

Ein 3B-Modell (Q4) braucht ca. 2 bis 3 GB RAM und ist auf CPU langsam. Daher: Modell wird nur bei Bedarf geladen, KI-Jobs laufen im Hintergrund und sind abbrechbar, Speicherverbrauch im Dashboard oder Log sichtbar. Realistische Laufzeiten dokumentieren, nicht schätzen.

## 15. Vorgehen (mit Freigabepunkten)

**Phase 1 (zuerst, dann STOPP und Freigabe abwarten):** Anforderungen auf Widersprüche prüfen, Architekturvorschlag, Technologien, Datenmodell, API, Risiken, Implementierungsplan. Noch kein umfangreicher Code.

Danach jeweils mit kurzem Bericht (was umgesetzt, wie getestet) und Freigabe vor der nächsten Gruppe:

- Gruppe A: Phase 2 und 3 (Grundprojekt, Excel-Import, Spaltenerkennung)
- Gruppe B: Phase 4 und 5 (Regelengine, Vergleich, Matching-Kaskade)
- Gruppe C: Phase 6 und 7 (lokale KI, UI)
- Gruppe D: Phase 8, 9, 10 (Export, Tests vervollständigen, Installer)

Der MVP umfasst: Import, Analyse, Hersteller erkennen, Regeln anwenden, Vergleich, Anzeige, Export, KI für schwierige Fälle. Alles andere später.

## 16. Prioritäten

Sicherheit, Offline-Betrieb, Datenschutz und mathematische Korrektheit haben Vorrang vor KI-Funktionalität. Wenn eine Entscheidung fehlt, die das Ergebnis wesentlich beeinflusst (z. B. Berechnungsbasis, Rundung, Schwellwerte), nachfragen statt annehmen.
