# Akten — Kanzlei V3

## Was ist eine Akte?
Eine Akte repräsentiert einen Rechtsfall. Jeder Fall (Verkehrsunfall, Schadenersatz usw.)
wird als eigene Akte geführt. Die Akte enthält alle zugehörigen Informationen:
Mandant, Gegner, Drittbeteiligte, Dokumente, Fristen, Aufgaben und Finanzen.

## Aktenzeichen
Das Aktenzeichen ist die eindeutige Kennung einer Akte. Format: MM.JJ.NNN
- MM = laufende Mandantennummer (zweistellig)
- JJ = Jahr (zweistellig, z.B. 26 für 2026)
- NNN = laufende Fallnummer (dreistellig)
Beispiel: 01.26.042 = Mandant 1, Jahr 2026, Fall 42.

## Status-Werte einer Akte
- Offen: Akte ist aktiv in Bearbeitung
- Geschlossen: Fall abgeschlossen, keine weiteren Aktionen
- Archiviert: Akte archiviert (Langzeitspeicherung)

## Felder einer Akte
- aktenzeichen (Pflicht, eindeutig)
- mandant (Verknüpfung zum Mandanten)
- gegner (Verknüpfung zur Gegnerpartei / Versicherung)
- drittbeteiligte (weitere Beteiligte)
- status (Offen / Geschlossen / Archiviert)
- fragebogen_data (JSON: Unfalldetails: Datum, Ort, Hergang, Kennzeichen, Personenschaden usw.)
- sachbearbeiter (zuständiger Mitarbeiter)
- erstellt_am, aktualisiert_am

## Fragebogen-Daten (fragebogen_data)
- datum_zeit: Datum und Uhrzeit des Unfalls
- unfallort: Ort des Unfalls
- gegner_kennzeichen: Kennzeichen des Unfallgegners
- polizei: Boolean ob Polizei aufgenommen
- personenschaden: Boolean ob Personenschäden vorhanden
- sv_beauftragt: Boolean ob Sachverständiger beauftragt
- versicherungsscheinnummer: Nummer der gegnerischen Versicherung

## Neue Akte anlegen
1. Im Menü auf "Akten" klicken
2. "Neue Akte" Button klicken
3. Mandant auswählen oder neu anlegen
4. Gegner (Versicherung) auswählen oder neu anlegen
5. Fragebogen ausfüllen (Unfalldetails)
6. Speichern → Aktenzeichen wird automatisch vergeben

## Akte suchen und filtern
- Nach Status filtern (Offen, Geschlossen, Archiviert)
- Nach Sachbearbeiter filtern
- Nach Monat und Jahr filtern
- Volltextsuche nach Aktenzeichen oder Mandantenname
