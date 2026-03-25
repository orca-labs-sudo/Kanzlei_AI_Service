# Mandanten und Gegner — Kanzlei V3

## Was ist ein Mandant?
Ein Mandant ist der Auftraggeber der Kanzlei. Pro Akte gibt es genau einen Mandanten.
Mandanten können in mehreren Akten vorkommen.

## Felder eines Mandanten
- vorname, nachname (Pflicht)
- ansprache: "Herr" oder "Frau" (für Anschreiben)
- strasse, hausnummer, plz, stadt (Adresse)
- telefon, email
- bankverbindung (IBAN)
- vst_berechtigt: Boolean — vorsteuerabzugsberechtigt?
- empfehlung: Freitext — wie kam der Mandant zur Kanzlei?
  Beispiele: "Google Ads", "Empfehlung Max Müller", "Webseite", "Facebook"

## Gegner / Versicherung
Ein Gegner ist die Gegenpartei (meist eine KFZ-Haftpflichtversicherung). Felder:
- name (Pflicht, z.B. "Allianz Versicherung AG", "HUK Coburg", "MDT")
- strasse, plz, stadt
- email, telefon

## Ansprache in Briefen
"Herr" → Anschreiben beginnt mit "Sehr geehrter Herr Nachname"
"Frau" → Anschreiben beginnt mit "Sehr geehrte Frau Nachname"

## Empfehlung abfragen
Loki kann nach Empfehlungen filtern:
"Welche Mandanten kamen im März über Google?" → get_akten_by_empfehlung(empfehlung="Google", monat=3)
"Wieviele Mandanten hat Herr Müller empfohlen?" → get_akten_by_empfehlung(empfehlung="Müller")
