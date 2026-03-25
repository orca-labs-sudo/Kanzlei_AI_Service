# Dokumente — Kanzlei V3

## Was sind Dokumente?
Dokumente sind alle Dateien und Schriftstücke die einer Akte zugeordnet sind.
Jedes Dokument hat einen Titel, eine Kategorie und einen Speicherpfad.

## Dokumenten-Kategorien
- Korrespondenz: Briefe, E-Mails, Schreiben
- KI-Entwurf: Von der KI generierte Briefentwürfe
- Gutachten: Sachverständigengutachten
- Polizeiprotokoll: Unfallberichte der Polizei
- Rechnung: Rechnungen (Reparatur, Sachverständiger)
- Vollmacht: Vollmachtsdokumente
- Sonstiges: Andere Dokumente

## Generierte Dokumente (GeneriertesDokument)
Wenn Loki oder das DraftingStudio einen Brief erstellt wird ein GeneriertesDokument angelegt.
Es enthält den vollständigen Brieftext (mit Briefkopf, Signatur) und kann als PDF heruntergeladen werden.

## PDF-Download
Generierte Dokumente können als PDF heruntergeladen werden.
Endpunkt: /api/documents/dokumente/{id}/download/
Das PDF wird mit WeasyPrint gerendert (professionelle Qualität).

## E-Mail als Dokument
Eingehende E-Mails (.eml-Dateien) können manuell hochgeladen und einer Akte zugeordnet werden.
Das System extrahiert Absender, Betreff und Inhalt automatisch.

## Akten ohne Dokument abfragen
Loki kann Akten ohne bestimmte Dokumente finden:
"Welche Akten haben noch kein Erstanschreiben?" → get_akten_ohne_dokument(dokument_stichwort="Erstanschreiben")
"Zeig alle offenen Akten ohne Vollmacht" → get_akten_ohne_dokument(dokument_stichwort="Vollmacht", status="Offen")
