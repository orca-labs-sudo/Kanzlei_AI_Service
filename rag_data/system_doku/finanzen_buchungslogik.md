# Finanzen und Buchungslogik (Kanzlei V3)

Dieses Dokument beschreibt die Buchungs- und Finanzlogik im Kanzlei V3 System. Es dient als Referenz für die korrekte Anlage, Verwaltung und Klassifizierung von Zahlungen, Forderungen und fiktiven Abrechnungen in Mandantenakten.

## 1. Konzept: Buchungstypen

Das System unterscheidet Zahlungen (Bankbewegungen) in drei grundlegende Buchungstypen. Diese Typen bestimmen, wie sich eine Zahlung auf den Saldo der Akte (Haben-Betrag) oder die Weiterleitungs-Summe auswirkt.

*   **EINGANG (Zahlungseingang):** 
    Eine positive Bankbewegung (Betrag > 0). Die Zahlung erfolgt von einer Drittpartei (Versicherung, Gegner, Gericht oder Mandant) auf das Kanzleikonto.
    *   **Auswirkung:** Erhöht den `haben_betrag` (Erhalten-Betrag) der verknüpften Position. Reduziert die noch offene Forderung.

*   **WEITERLEITUNG (Auszahlung an Mandant):**
    Eine negative Bankbewegung (Betrag < 0). Die Kanzlei leitet eingegangene Fremdgelder (z.B. Reparaturkosten, Schmerzensgeld) auf das Konto des Mandanten weiter. 
    *   **Auswirkung:** Ein solcher Ausgang verändert *nicht* den `haben_betrag` der Position (das Geld wurde ja gegenüber dem Gegner erfolgreich realisiert). Stattdessen wird die Zahlung rein als Weiterleitung verbucht (erhöht den internen `weiterleitung_betrag`), um buchhalterisch zu dokumentieren, dass das Mandantengeld abgeflossen ist.

*   **GEBUEHR (Bankgebühr):**
    Eine negative Bankbewegung (Betrag < 0) ohne Bezug zu einer Mandantenakte (z.B. Kontoführungsgebühren, Kartengebühren, Zinsen, Buchungsentgelte).
    *   **Auswirkung:** Wird vom Kanzlei-Matching (Loki) ignoriert und keiner Akte zugeordnet (`zahlungsabgleich_id` = null). Die Bewegung taucht im Aktenkonto nicht auf.

### Beispiel: Typischer Ablauf eines Forderungseingangs und der Weiterleitung

| Datum      | Buchungstyp   | Akteur            | Betrag    | Zuordnung zur Position | Auswirkung in der Akte |
|:-----------|:--------------|:------------------|:----------|:-----------------------|:-----------------------|
| 10.05.2026 | EINGANG       | Versicherung X    | +461,86 € | Wertminderung          | `haben_betrag` steigt um 461,86 € (Zahlung erledigt) |
| 11.05.2026 | WEITERLEITUNG | an Mandant Müller | -461,86 € | Wertminderung          | `haben_betrag` bleibt gleich. `weiterleitung_betrag` steigt. Geld ist beim Mandanten. |
| 31.05.2026 | GEBUEHR       | Sparkasse / Bank  | -12,50 €  | (Keine Akte)           | Buchhalterischer Abgang, wird in den Akten ignoriert. |


## 2. Konzept: Position-Modus (Steuerliche Behandlung)

Jede Forderungsposition in der Akte hat einen definierten Steuer-Modus, der steuert, wie Brutto- und Nettobeträge berechnet und verbucht werden.

*   **brutto (19% USt):** 
    Der Standardmodus für anwaltliche Gebühren (RVG) oder reparierte Sachschäden (wenn der Mandant nicht vorsteuerabzugsberechtigt ist). 
    *   Soll- und Haben-Beträge in der Datenbank sind *immer* Bruttobeträge.
    *   Das Netto wird vom Frontend/System dynamisch über den USt-Satz (z.B. 19%) errechnet.

*   **netto (0% USt):** 
    Typischerweise bei fiktiver Abrechnung (siehe Abschnitt 3) oder wenn der Mandant Unternehmer (vorsteuerabzugsberechtigt) ist und die USt selbst trägt.
    *   Die Forderung wird netto geltend gemacht.
    *   USt fällt für diese Position nicht an (0%).

*   **ohne_ust (Schadenersatz nach § 249 BGB):**
    Positionen, die von Natur aus nicht umsatzsteuerpflichtig sind. Dazu gehören u.A.:
    *   Wertminderung
    *   Nutzungsausfall / Schmerzensgeld
    *   Allgemeine Auslagenpauschale (Kostenpauschale)
    *   In diesem Modus gilt stets: Bruttobetrag = Nettobetrag. Es wird keine Steuer ausgewiesen.


## 3. Fiktive Abrechnung

Die fiktive Abrechnung tritt häufig im Verkehrsrecht auf. Sie bedeutet, dass ein Unfallschaden laut Gutachten kalkuliert wird, das Fahrzeug aber nicht (oder nicht fachgerecht mit Rechnung) repariert wird. Alternativ ist der Mandant Unternehmer und zum Vorsteuerabzug berechtigt. In beiden Fällen darf die Versicherung die Reparaturkosten nur *netto* (ohne USt) erstatten.

**System-Ablauf bei Umstellung auf fiktive Abrechnung:**
1. Die Kanzlei macht ursprünglich z.B. 1.000 € (Brutto) als Reparaturkosten geltend.
2. Es stellt sich heraus: Der Mandant repariert nicht. Die Forderung muss auf "netto" korrigiert werden.
3. Die Original-Brutto-Position (1.000 €) wird im System auf den Status `ersetzt` (deaktiviert) gesetzt.
4. Es wird automatisch eine **neue Netto-Kind-Position** angelegt (mit dem errechneten Nettobetrag, z.B. 840,34 €). Diese neue Position verweist über das Feld `fiktiv_parent` auf die alte Brutto-Position.
5. **Aus Sicht der Akte:** Die alte Brutto-Position ist historisch dokumentiert, aber durch den Status `ersetzt` nicht mehr forderungswirksam. Nur die neue Netto-Position ist aktiv (z.B. Status `offen`).


## 4. Position-Status

Der Status einer Position (Forderung) dokumentiert deren aktuellen Zahlungsstand. Loki und das Backend aktualisieren diesen Status teilweise automatisch anhand der Bankbewegungen.

| Status | Beschreibung | Automatik-Wechsel |
|:---|:---|:---|
| **offen** | Die Forderung ist fällig, es liegt bisher kein Zahlungseingang vor. | Default bei Neuanlage. |
| **teilzahlung** | Es ging Geld ein, aber der Betrag reicht nicht aus, um die volle Summe (`soll_betrag`) zu decken. | Wechselt automatisch durch Loki/Backend, wenn `haben_betrag` > 0 aber < `soll_betrag`. |
| **erledigt** | Die Position ist vollständig bezahlt (oder vom Anwalt ausgebucht). | Wechselt automatisch, sobald `haben_betrag` >= `soll_betrag`. |
| **strittig** | Die Gegenseite verweigert die (vollständige) Zahlung (z.B. Versicherung kürzt Wertminderung). | Muss manuell gesetzt werden, um Klagewahrscheinlichkeit zu prüfen. |
| **ersetzt** | Position ist nicht mehr aktiv (siehe Fiktive Abrechnung). | Automatisch beim Klick auf "Auf Fiktiv umstellen". |


## 5. Beispiele aus dem Verkehrsrecht

Um die Theorie in die Praxis umzusetzen, hier drei häufige Buchungsszenarien im anwaltlichen Kanzleialltag:

### Szenario A: RVG-Abrechnung (Versicherung zahlt Anwaltskosten)
*   **Fakt:** Mandant ist Privatperson (kein Vorsteuerabzug).
*   **Aktion:** Kanzlei fordert 500,00 € RVG-Gebühr.
*   **Modus:** `brutto` (19% USt in den 500,00 € enthalten).
*   **Zahlung:** Versicherung überweist 500,00 € direkt auf das Kanzleikonto.
*   **Buchungstyp:** `EINGANG`
*   **Ergebnis:** `haben_betrag` wird 500,00 €. Status wechselt von `offen` auf `erledigt`. Die Kanzlei behält das Geld (als Honorar), keine Weiterleitung an den Mandanten.

### Szenario B: Fiktive Abrechnung von Reparaturkosten + Weiterleitung
*   **Fakt:** Mandant rechnet fiktiv ab.
*   **Aktion:** Reparaturkosten wurden auf fiktiv umgestellt. Es existiert eine aktive Netto-Position (z.B. 1.000 €).
*   **Modus:** `netto` (0% USt).
*   **Zahlung 1:** Versicherung überweist 1.000 € an die Kanzlei (`EINGANG`). Status wechselt auf `erledigt`.
*   **Zahlung 2:** Kanzlei leitet am Folgetag 1.000 € an den Mandanten weiter (`WEITERLEITUNG`).
*   **Ergebnis:** Die Akte weist aus: 1.000 € erhalten (`haben_betrag`), 1.000 € weitergeleitet (`weiterleitung_betrag`). Das Mandantengeld ist sauber durchgebucht.

### Szenario C: Versicherung kürzt Schadenersatz
*   **Fakt:** Kanzlei macht 800,00 € Wertminderung geltend.
*   **Modus:** `ohne_ust` (da Schadenersatz nach § 249 BGB).
*   **Zahlung:** Versicherung zahlt nur 500,00 € und übermittelt ein Kürzungsschreiben.
*   **Buchungstyp:** `EINGANG` über 500,00 €.
*   **Ergebnis:** Der Status springt automatisch auf `teilzahlung` (`haben_betrag` = 500,00 €). Die Kanzlei muss nun prüfen, ob der Restbetrag (300,00 €) eingeklagt wird. Ist dies der Fall, wird die Position manuell auf `strittig` gesetzt. Akzeptiert der Mandant die Kürzung, verbucht der Anwalt die restlichen 300,00 € als Verzicht, wodurch der Status auf `erledigt` (oder `gekuerzt_akzeptiert`) springt.


## 6. Formate / Konventionen für die Kanzlei-Software

Für eine einheitliche und revisionssichere Buchhaltung gelten im Code und System folgende Standards:

1.  **Brutto als Basis-Referenz:** 
    Datenbankfelder wie `soll_betrag` und `haben_betrag` speichern standardmäßig den vollen Bruttowert der jeweiligen Position. Berechnungen für Netto/Steuer erfolgen dynamisch basierend auf dem `modus`.
2.  **Ist-Versteuerung (eingegangen_datum):** 
    Alle steuerlichen Zeitpunkte richten sich nach dem Buchungsdatum der Bank (`eingegangen_datum`). Das Rechnungsdatum ist im Kanzlei-Alltag weniger relevant, da das Zuflussprinzip / die Ist-Versteuerung angewandt wird.
3.  **Audit-Trail via Notizen:** 
    Jeder Zahlungsabgleich besitzt ein `notiz`-Feld. Dort dokumentiert das System oder der Nutzer wichtige Änderungen, Teilzahlungsgründe oder Loki-Begründungen. Die Notiz fungiert als Audit-Trail.
