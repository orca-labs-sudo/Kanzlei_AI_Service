# Finanzen — Kanzlei V3

## Überblick
Das Finanzmodul erfasst alle Zahlungspositionen einer Akte: Forderungen an die Versicherung,
RVG-Gebühren, Auslagen, Sachverständigenkosten usw.

## Zahlungsposition (Modell)
Jede Zahlungsposition gehört zu einer Akte und hat folgende Felder:
- beschreibung: Was wird gefordert (z.B. "RVG-Grundgebühr", "Reparaturkosten", "Nutzungsausfall")
- soll_betrag: Geforderter Betrag in Euro
- haben_betrag: Eingegangener Betrag (Zahlung der Versicherung)
- status: "offen", "teilweise_bezahlt", "beglichen"
- aktiv: Boolean — ob Position aktiv ist
- erstellt_am

## Soll / Haben Logik
- Soll: Was die Versicherung zahlen soll (Forderung)
- Haben: Was tatsächlich eingegangen ist
- Differenz = offener Betrag

## RVG-Gebühren
RVG = Rechtsanwaltsvergütungsgesetz. Typische Positionen:
- 1.3 Geschäftsgebühr (außergerichtlich)
- Telekommunikationspauschale
- Akteneinsicht
- Fahrtkosten
Die Kanzlei nutzt einen RVG-Rechner der automatisch die Gebühren berechnet.

## Offene Beträge abfragen
Loki kann offene Beträge abrufen:
"Welche offenen Beträge gibt es im März?" → get_offene_betraege(monat=3, jahr=2026)
"Zeig alle offenen Positionen" → get_offene_betraege()

## Zahlungsabgleich
Ein Zahlungsabgleich vergleicht Soll und Haben einer Akte:
- Wenn Soll = Haben: Fall finanziell abgeschlossen
- Wenn Haben < Soll: Restforderung offen
