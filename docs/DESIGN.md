# Design Sales Assistant

Gilt für die App-Oberfläche (`frontend/static/style.css`, `frontend/templates/base.html`). Das Datenblatt hat sein
eigenes, festes Drucklayout (`frontend/static/datasheet.css`). Bei neuen Seiten diese Regeln einhalten; die Anleitung
`.claude/skills/frontend-design/SKILL.md` gilt zusätzlich.

## Grundidee
Braun & Braun macht Warn- und Signaltechnik für Fahrzeuge. Die Oberfläche ist ein ruhiges Werkzeug für den Vertrieb:
viel Fläche, klare Tabellen, Farbe nur mit Bedeutung.

## Farben (Tokens in `:root`, Dunkelmodus automatisch)
| Token | Hell | Bedeutung |
|---|---|---|
| `--bg` | #eef0f3 | Fläche (kühles Asphaltgrau) |
| `--surface` | #ffffff | Karten, Tabellen, Kopfleiste |
| `--fg` | #172033 | Text |
| `--accent` | #213984 | B&B-Blau – nur Akzent: Hauptknopf, aktive Navigation, Links, Titelbalken |
| `--signal` | #e58a00 | Warnlicht-Amber – nur für „braucht Aufmerksamkeit“ (offene Prüfungen, Hinweise) |
| `--ok` / `--err` | #1b7a45 / #b3261e | Status in Ordnung / Fehler |

## Schrift
Barlow (Verkehrsschild-Grotesk) für Text, Barlow Semi Condensed für Überschriften und Kennzahlen. Lokal ausgeliefert
(`frontend/static/fonts`, OFL), keine externen Schriftquellen. Zahlen in Tabellen mit Tabellenziffern.

## Regeln
- Erkennungszeichen: blauer Balken vor dem Seitentitel (wie im Datenblatt-Kopf). Sonst keine Deko.
- Keine Schatten auf Karten, nur 1px-Linien. Radien: 10px Flächen, 6px Bedienelemente, 4px Status-Tags.
- Keine Großbuchstaben-Labels, keine Überzeilen („Eyebrows“), keine Pfeile in Buttontexten, keine Farbverläufe.
- Navigation oben: Kernablauf als Reiter, Seltenes unter „Weitere“; ein Hauptknopf „Liste einspielen“.
- Offene Zeilen/Aufgaben: Amber-Streifen links. Rot nur für echte Fehler.
- Schnell bleiben: Server-HTML, reines CSS, nur kleine Scripts; keine Frameworks, keine externen Ressourcen.
