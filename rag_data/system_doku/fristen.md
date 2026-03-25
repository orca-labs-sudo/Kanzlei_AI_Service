# Fristen und Aufgaben — Kanzlei V3

## Was sind Fristen?
Fristen sind rechtliche oder interne Deadlines die einer Akte zugeordnet sind.
Beispiele: Verjährungsfrist, Antwortfrist der Versicherung, Klagefrist.

## Felder einer Frist
- bezeichnung: Name der Frist (z.B. "Antwortfrist Versicherung", "Verjährungsfrist")
- akte: Zugehörige Akte
- frist_datum: Datum bis wann die Frist läuft
- prioritaet: "hoch", "mittel", "niedrig"
- status: "offen", "erledigt", "überfällig"
- notiz: Freitext-Notiz zur Frist

## Fristen abfragen
Loki kann bevorstehende Fristen abrufen:
"Welche Fristen laufen in den nächsten 14 Tagen ab?" → get_fristen_naechste_tage(tage=14)
"Zeig alle Fristen der nächsten 30 Tage" → get_fristen_naechste_tage(tage=30)
"Welche Fristen laufen diese Woche ab?" → get_fristen_naechste_tage(tage=7)

## Aufgaben
Aufgaben sind interne To-Dos die einer Akte zugeordnet sind.
Felder:
- titel: Kurzbeschreibung der Aufgabe
- beschreibung: Ausführliche Beschreibung
- faellig_am: Fälligkeitsdatum
- status: "offen", "in_bearbeitung", "erledigt"
- zugewiesen_an: Sachbearbeiter

## Automatische Aufgaben
Das System erstellt automatisch eine Aufgabe "Bitte prüfen und versenden"
wenn ein KI-Brief generiert wird. Die KI versendet niemals selbständig.

## Standard-Frist nach § 115 VVG
Nach § 115 VVG hat die Versicherung 3 Monate Zeit zur Regulierung.
Die Kanzlei setzt standardmäßig eine 14-Tage-Antwortfrist im Erstanschreiben.
