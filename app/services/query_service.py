"""
Query Service — MCP-Sekretärin (Task C2)

Verarbeitet Freitext-Anfragen via Gemini Function Calling und übersetzt sie
in strukturierte Django-API-Aufrufe. Gibt formatierte Ergebnisse zurück.

Ablauf:
  1. Freitext-Query empfangen
  2. Gemini Function Calling → Tool + Parameter bestimmen
  3. Django /api/ai/query/* Endpoint aufrufen
  4. Ergebnis für Frontend formatieren
"""
import httpx
import logging
from typing import Any, Dict, List, Optional

from app.config import settings

logger = logging.getLogger(__name__)

import re as _re_module


def _strip_markdown(text: str) -> str:
    """Entfernt Markdown-Formatierung aus LLM-Antworten (Post-Processing-Fallback)."""
    # **bold** → bold
    text = _re_module.sub(r'\*\*(.+?)\*\*', r'\1', text)
    # *italic* → italic
    text = _re_module.sub(r'\*(.+?)\*', r'\1', text)
    # ## Überschriften → Text
    text = _re_module.sub(r'^#{1,6}\s+', '', text, flags=_re_module.MULTILINE)
    # - oder * Aufzählungszeichen am Zeilenanfang entfernen
    text = _re_module.sub(r'^[-*]\s+', '', text, flags=_re_module.MULTILINE)
    return text


# ===========================================================================
# TOOL-DEFINITIONEN für Gemini Function Calling
# ===========================================================================

TOOL_DECLARATIONS: List[Dict] = [
    {
        "name": "get_akten_liste",
        "description": (
            "Liste aller Akten (Rechtsfälle) abrufen. "
            "Kann nach Status, Monat, Jahr und Sachbearbeiter gefiltert werden."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Aktenstatus: 'Offen', 'Geschlossen' oder 'Archiviert'",
                },
                "monat": {
                    "type": "integer",
                    "description": "Monat (1–12), bezieht sich auf erstellt_am",
                },
                "jahr": {
                    "type": "integer",
                    "description": "Jahr (z.B. 2026)",
                },
                "sachbearbeiter": {
                    "type": "string",
                    "description": "Name des Sachbearbeiters/Referenten (Teilstring-Suche)",
                },
            },
        },
    },
    {
        "name": "get_offene_betraege",
        "description": (
            "Offene (noch nicht bezahlte) Zahlungspositionen mit Soll- und Habenbeträgen abrufen. "
            "Kann nach Monat und Jahr gefiltert werden."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "monat": {
                    "type": "integer",
                    "description": "Monat (1–12)",
                },
                "jahr": {
                    "type": "integer",
                    "description": "Jahr (z.B. 2026)",
                },
            },
        },
    },
    {
        "name": "count_faelle",
        "description": (
            "Anzahl der Fälle (Akten) zählen, optional gefiltert nach Sachbearbeiter, Jahr und Status."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sachbearbeiter": {
                    "type": "string",
                    "description": "Name des Sachbearbeiters/Referenten (Teilstring-Suche)",
                },
                "jahr": {
                    "type": "integer",
                    "description": "Jahr (z.B. 2026)",
                },
                "status": {
                    "type": "string",
                    "description": "Aktenstatus: 'Offen', 'Geschlossen' oder 'Archiviert'",
                },
            },
        },
    },
    {
        "name": "get_akten_ohne_fragebogen",
        "description": (
            "Alle Akten abrufen, bei denen noch kein Fragebogen ausgefüllt wurde "
            "(fehlende Unfalldetails, Daten unvollständig)."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_fristen_naechste_tage",
        "description": (
            "Alle offenen Fristen (Deadlines) abrufen, die in den nächsten N Tagen ablaufen. "
            "Standard: 30 Tage."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tage": {
                    "type": "integer",
                    "description": "Anzahl der Tage voraus (Standard: 30)",
                },
            },
        },
    },
    {
        "name": "get_akte_by_aktenzeichen",
        "description": "Eine bestimmte Akte anhand ihres Aktenzeichens (z.B. '01.26.XYZ') abrufen.",
        "parameters": {
            "type": "object",
            "properties": {
                "aktenzeichen": {
                    "type": "string",
                    "description": "Das Aktenzeichen der gesuchten Akte",
                },
            },
            "required": ["aktenzeichen"],
        },
    },
    {
        "name": "get_akten_by_empfehlung",
        "description": (
            "Akten abrufen, deren Mandant über eine bestimmte Empfehlung/Quelle kam. "
            "Z.B. 'Wie viele Akten wurden im März auf Empfehlung von Max geöffnet?' "
            "Kann nach Monat und Jahr gefiltert werden."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "empfehlung": {
                    "type": "string",
                    "description": "Name oder Quelle der Empfehlung (Teilstring-Suche), z.B. 'Max', 'Google Ads'",
                },
                "monat": {
                    "type": "integer",
                    "description": "Monat (1–12)",
                },
                "jahr": {
                    "type": "integer",
                    "description": "Jahr (z.B. 2026)",
                },
            },
            "required": ["empfehlung"],
        },
    },
    {
        "name": "get_akten_ohne_dokument",
        "description": (
            "Akten abrufen, die ein bestimmtes Dokument NICHT enthalten. "
            "Z.B. Akten ohne Erstanschreiben, ohne Klageschrift, ohne Vollmacht. "
            "Kann zusätzlich nach Gegner (Versicherung) und Status gefiltert werden."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "dokument_stichwort": {
                    "type": "string",
                    "description": "Stichwort im Dokumenttitel, z.B. 'Erstanschreiben', 'Vollmacht', 'Klageschrift'",
                },
                "gegner": {
                    "type": "string",
                    "description": "Name der Gegnerpartei/Versicherung (Teilstring), z.B. 'MDT', 'HUK', 'Allianz'",
                },
                "status": {
                    "type": "string",
                    "description": "Aktenstatus: 'Offen', 'Geschlossen' oder 'Archiviert'",
                },
            },
            "required": ["dokument_stichwort"],
        },
    },
    {
        "name": "get_akten_by_gegner",
        "description": (
            "Alle Akten einer bestimmten Gegnerpartei oder Versicherung abrufen. "
            "Z.B. alle Fälle gegen MDT, HUK, Allianz."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "gegner": {
                    "type": "string",
                    "description": "Name der Gegnerpartei/Versicherung (Teilstring-Suche), z.B. 'MDT', 'HUK'",
                },
            },
            "required": ["gegner"],
        },
    },
    {
        "name": "erstelle_brief_aus_kontext",
        "description": "Erstellt einen professionellen Brieftext wenn der User einen Text/Begründung eingibt und daraus einen Brief formuliert haben möchte.",
        "parameters": {
            "type": "object",
            "properties": {
                "user_kontext": {
                    "type": "string",
                    "description": "Der vom User eingefügte Text / die Begründung"
                },
                "schreiben_typ": {
                    "type": "string",
                    "description": "widerspruch | anfrage | mahnung | sonstig"
                }
            },
            "required": ["user_kontext"],
        },
    },
    {
        "name": "sync_frist_zu_calendar",
        "description": (
            "Synchronisiert eine Frist oder Aufgabe in Google Calendar. "
            "Wenn der User sagt: 'Leg die Frist in den Kalender' oder "
            "'Widerspruchsfrist am 15.04. eintragen'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "akte_id": {
                    "type": "integer",
                    "description": "ID der Akte"
                },
                "titel": {
                    "type": "string",
                    "description": "Titel, z.B. 'Widerspruchsfrist'"
                },
                "datum": {
                    "type": "string",
                    "description": "Datum im Format YYYY-MM-DD"
                },
                "beschreibung": {
                    "type": "string",
                    "description": "Optionale Beschreibung"
                },
            },
            "required": ["akte_id", "titel", "datum"],
        }
    },
    {
        "name": "sende_email_an_gegner",
        "description": (
            "Sendet eine E-Mail an den Gegner (z.B. Versicherung) der aktuellen Akte. "
            "Wenn der User sagt: 'Schick das an die Allianz' oder "
            "'E-Mail an den Gegner mit dem Widerspruch'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "akte_id": {
                    "type": "integer",
                    "description": "ID der Akte"
                },
                "betreff": {
                    "type": "string",
                    "description": "E-Mail-Betreff"
                },
                "text": {
                    "type": "string",
                    "description": "E-Mail-Text (Fliesstext)"
                },
                "dokument_id": {
                    "type": "integer",
                    "description": "Optional: ID des anzuhängenden Dokuments"
                },
            },
            "required": ["akte_id", "betreff", "text"],
        }
    }
]


# ===========================================================================
# HILFSFUNKTIONEN
# ===========================================================================

def _tab_hinweis(active_tab: str) -> str:
    hinweise = {
        "dokumente": "Fokus: Dokumente — Inhalte erklären, PDF-Umwandlung vorschlagen.",
        "finanzen":  "Fokus: Finanzen — RVG-Berechnung, Zahlungspositionen, offene Beträge.",
        "uebersicht": "Fokus: Kurzer Statusüberblick, nächster offener Schritt.",
        "ki":        "Fokus: Vollständige Workflow-Unterstützung — Analyse, Briefe, Aktionen.",
    }
    return hinweise.get(active_tab, "")


# ===========================================================================
# QUERY SERVICE
# ===========================================================================

class QueryService:
    """
    Verarbeitet Freitext-Anfragen via Gemini Function Calling
    und ruft die entsprechenden Django /api/ai/query/* Endpoints auf.
    """

    def __init__(self):
        self.django_base = settings.backend_url.rstrip("/")
        self.django_headers = {
            "Authorization": f"Bearer {settings.backend_api_token}",
            "Content-Type": "application/json",
        }

    async def handle_query(self, query: str, user_id: int, akte_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Haupteinstiegspunkt: Freitext → Gemini/Vertex → Tool-Call → Django → formatiertes Ergebnis.
        """
        from app.main import get_gemini_client
        if not get_gemini_client():
            return {"status": "error", "error": "KI-Dienst nicht bereit."}

        # cast for pyre
        safe_query = str(query) if query else ""
        logger.info(f"QueryService: Verarbeite Anfrage von User {user_id}: '{safe_query[:80]}'")

        # 1. Gemini Function Calling → Tool + Parameter bestimmen
        function_call = await self._classify_with_gemini(query)

        if not function_call:
            logger.info("Kein Tool gewählt -> Fallback auf System-Wissen RAG")
            return await self._handle_rag_fallback(query)

        tool_name = str(function_call.get("name", ""))
        tool_args = function_call.get("args", {})
        logger.info(f"Gemini wählte Tool: {tool_name}, Args: {tool_args}")

        # 2. Django-Endpoint aufrufen
        raw_data = await self._execute_tool(tool_name, tool_args, akte_id)

        if raw_data is None:
            return {
                "status": "error",
                "error": f"Datenbankabfrage für '{tool_name}' fehlgeschlagen.",
            }

        if not isinstance(raw_data, dict) and not isinstance(raw_data, list):
            return {
                "status": "error",
                "error": f"Ungültiges Rückgabeformat für '{tool_name}'.",
            }

        # 3. Ergebnis für Frontend aufbereiten
        return self._format_result(tool_name, raw_data)

    # -----------------------------------------------------------------------
    # Gemini Function Calling
    # -----------------------------------------------------------------------

    async def _classify_with_gemini(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Sendet die Anfrage an Gemini/Vertex mit Function Calling (neues SDK).
        Gibt den gewählten Tool-Call zurück oder None wenn kein Tool passt.
        """
        from app.main import get_gemini_client
        from google.genai import types as genai_types

        gemini = get_gemini_client()
        if not gemini:
            return None

        system_text = (
            "Du bist eine KI-Sekretärin für eine Kanzlei (Verkehrsrecht). "
            "Analysiere die Anfrage und wähle das passende Werkzeug aus. "
            "Wähle genau ein Werkzeug. Wenn keine Anfrage zu den Werkzeugen passt, "
            "antworte ohne Werkzeug-Aufruf."
        )

        config = genai_types.GenerateContentConfig(
            tools=[{"function_declarations": TOOL_DECLARATIONS}],
            system_instruction=system_text,
            temperature=0.0,
        )

        try:
            response = await gemini.client.aio.models.generate_content(
                model=gemini.model_name,
                contents=query,
                config=config,
            )

            if response.candidates and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    fc = getattr(part, "function_call", None)
                    if fc:
                        return {"name": fc.name, "args": dict(fc.args)}

            logger.info("Gemini hat kein Tool gewählt (kein passender Befehl).")
            return None

        except Exception as e:
            logger.error(f"Gemini Function Calling Fehler: {e}")
            return None

    async def _handle_rag_fallback(self, query: str) -> Dict[str, Any]:
        """Sucht im system_wissen via RAG und generiert eine Antwort mit Gemini."""
        from app.services.rag_store import rag_store
        
        # 1. RAG-Abfrage in der System-Doku
        matches = await rag_store.search_similar(query_text=query, n_results=3, collection_name="system_wissen")
        
        if not matches:
            return {
                "status": "ok",
                "result_type": "text",
                "data": (
                    "Ich konnte die Anfrage leider keinem meiner Werkzeuge zuordnen "
                    "und habe dazu auch keine Informationen in meiner System-Doku gefunden. "
                    "Versuche es mit einer spezifischeren Frage."
                ),
                "query_used": "fallback",
            }
            
        # 2. Kontext zusammenbauen
        context_texts = []
        for match in matches:
            context_texts.append(match.get("text", ""))
        context_str = "\n\n---\n\n".join(context_texts)
        
        # 3. Antwort via neuem SDK generieren (Vertex AI oder Gemini)
        from app.main import get_gemini_client
        from google.genai import types as genai_types

        gemini = get_gemini_client()
        if not gemini:
            return {"status": "error", "error": "KI-Dienst nicht bereit."}

        system_prompt = (
            "Du bist ein hilfreicher Assistent für das Kanzlei-Programm. "
            "Beantworte die Frage des Nutzers AUSSCHLIESSLICH basierend auf dem folgenden System-Wissen. "
            "Erfinde keine Funktionen hinzu. Halte dich kurz und prägnant."
        )
        prompt = f"SYSTEM-WISSEN:\n{context_str}\n\nFRAGE DES NUTZERS:\n{query}"

        try:
            response = await gemini.client.aio.models.generate_content(
                model=gemini.model_name,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.2,
                ),
            )
            answer_text = response.text.strip() if response.text else ""
            if answer_text:
                return {
                    "status": "ok",
                    "result_type": "text",
                    "data": answer_text,
                    "query_used": "rag_system_wissen",
                }
            return {"status": "error", "error": "Konnte keine Antwort aus dem System-Wissen generieren."}
        except Exception as e:
            logger.error(f"Fehler bei der Fallback-Antwort Generierung: {e}")
            return {"status": "error", "error": "Fehler bei der Formulierung der System-Antwort."}

    # -----------------------------------------------------------------------
    # Tool-Dispatch → Django /api/ai/query/* Endpoints
    # -----------------------------------------------------------------------

    async def _execute_tool(self, tool_name: str, args: Dict[str, Any], akte_id: Optional[int] = None) -> Optional[Any]:
        """Routet den Tool-Call zum passenden Django-Endpoint."""
        tool_map = {
            "get_akten_liste": self._get_akten_liste,
            "get_offene_betraege": self._get_offene_betraege,
            "count_faelle": self._count_faelle,
            "get_akten_ohne_fragebogen": self._get_akten_ohne_fragebogen,
            "get_fristen_naechste_tage": self._get_fristen_naechste_tage,
            "get_akte_by_aktenzeichen": self._get_akte_by_aktenzeichen,
            "get_akten_by_empfehlung": self._get_akten_by_empfehlung,
            "get_akten_ohne_dokument": self._get_akten_ohne_dokument,
            "get_akten_by_gegner": self._get_akten_by_gegner,
            "erstelle_brief_aus_kontext": self._erstelle_brief_aus_kontext,
            "sync_frist_zu_calendar": self._sync_frist_zu_calendar,
            "sende_email_an_gegner": self._sende_email_an_gegner,
        }

        handler = tool_map.get(tool_name)
        if not handler:
            logger.warning(f"Unbekanntes Tool: {tool_name}")
            return None

        try:
            if tool_name == "erstelle_brief_aus_kontext":
                # Empfänger und Notizen optional durchschleifen, wenn sie im Request sind
                empfaenger = args.pop('empfaenger', 'versicherung')
                notizen = args.pop('notizen', '')
                # type: ignore (Pyre2: Typensignatur von handler ist dynamisch)
                return await handler(
                    user_kontext=args.get('user_kontext', ''),
                    schreiben_typ=args.get('schreiben_typ'),
                    akte_id=akte_id,
                    empfaenger=empfaenger,
                    notizen=notizen
                )
            return await handler(**args)  # type: ignore
        except Exception as e:
            logger.error(f"Tool-Ausführung fehlgeschlagen ({tool_name}): {e}")
            return None

    async def _get(self, path: str, params: Dict = None) -> Any:
        """Hilfsfunktion: GET-Request an Django /api/ai/query/ mit Bearer-Token."""
        url = f"{self.django_base}/api/ai/query/{path}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                url, params=params or {}, headers=self.django_headers
            )
            response.raise_for_status()
            return response.json()

    async def _get_akten_liste(
        self,
        status: str = None,
        monat: int = None,
        jahr: int = None,
        sachbearbeiter: str = None,
    ):
        params = {}
        if status:
            params["status"] = status
        if monat:
            params["monat"] = monat
        if jahr:
            params["jahr"] = jahr
        if sachbearbeiter:
            params["sachbearbeiter"] = sachbearbeiter
        return await self._get("akten/", params)

    async def _get_offene_betraege(self, monat: int = None, jahr: int = None):
        params = {}
        if monat:
            params["monat"] = monat
        if jahr:
            params["jahr"] = jahr
        return await self._get("offene_betraege/", params)

    async def _count_faelle(
        self,
        sachbearbeiter: str = None,
        jahr: int = None,
        status: str = None,
    ):
        params = {}
        if sachbearbeiter:
            params["sachbearbeiter"] = sachbearbeiter
        if jahr:
            params["jahr"] = jahr
        if status:
            params["status"] = status
        return await self._get("count_faelle/", params)

    async def _get_akten_ohne_fragebogen(self):
        return await self._get("akten_ohne_fragebogen/")

    async def _get_fristen_naechste_tage(self, tage: int = 30):
        return await self._get("fristen/", {"tage": tage})

    async def _get_akte_by_aktenzeichen(self, aktenzeichen: str):
        return await self._get("akte_by_az/", {"aktenzeichen": aktenzeichen})

    async def _get_akten_ohne_dokument(self, dokument_stichwort: str, gegner: str = None, status: str = None):
        params = {"dokument_stichwort": dokument_stichwort}
        if gegner: params["gegner"] = gegner
        if status: params["status"] = status
        return await self._get("akten_ohne_dokument/", params)

    async def _get_akten_by_gegner(self, gegner: str):
        return await self._get("akten_by_gegner/", {"gegner": gegner})

    async def _get_akten_by_empfehlung(self, empfehlung: str, monat: int = None, jahr: int = None):
        params = {"empfehlung": empfehlung}
        if monat: params["monat"] = monat
        if jahr: params["jahr"] = jahr
        return await self._get("akten_by_empfehlung/", params)

    async def _erstelle_brief_aus_kontext(
        self, 
        user_kontext: str, 
        schreiben_typ: str = None, 
        akte_id: int = None,
        empfaenger: str = 'versicherung',
        notizen: str = ''
    ):
        """
        N-G2 Tool Handler: Generiert einen Brief-Rohtext direkt hier im AI-Service.
        Erweitert um Akte-Daten via RAG.
        """
        from app.main import get_gemini_client
        gemini = get_gemini_client()
        if not gemini:
            return {"error": "Gemini API nicht bereit", "brief_text": "Lokale Generierung nicht möglich."}
        
        akte_context = ""
        rag_context = ""

        if akte_id:
            try:
                akte_data = await self._get("akte_by_id/", {"akte_id": akte_id})
                akte_context = (
                    f"Akte-Details:\n"
                    f"Aktenzeichen: {akte_data.get('aktenzeichen')}\n"
                    f"Mandant: {akte_data.get('mandant')}\n"
                    f"Gegner: {akte_data.get('gegner')}\n"
                    f"Unfallort: {akte_data.get('unfallort', getattr(akte_data, 'unfallort', ''))}\n"
                )
            except Exception as e:
                logger.warning(f"Konnte Akte {akte_id} Context nicht laden: {e}")

            try:
                from app.services.rag_store import rag_store
                matches = await rag_store.search_similar(user_kontext, n_results=3, collection_name="muster_schreiben")
                if matches:
                    muster_texts = [m.get("text", "") for m in matches]
                    rag_context = "Hier sind ähnliche Muster-Schreiben als Stil-Referenz:\n" + "\n---\n".join(muster_texts)
            except Exception as e:
                logger.warning(f"RAG-Suche in muster_schreiben fehlgeschlagen: {e}")
            
        system_instruction = (
            "Du bist ein erfahrener Rechtsanwalt. Formuliere einen professionellen "
            "Brieftext basierend auf dem vom Benutzer bereitgestellten Kontext.\n\n"
            "WICHTIG: Generiere NUR den Fließtext des Briefes — OHNE Anrede und OHNE Grußformel.\n"
            "KEIN Briefkopf, KEINE Adresse, KEIN Datum, KEIN Aktenzeichen, KEINE Anrede ('Sehr geehrte...').\n"
            "Anrede, Briefkopf und Signatur werden vom System automatisch ergänzt.\n"
            "Halte den rechtlichen Ton professionell und präzise."
        )
        
        prompt_parts = []
        if empfaenger == 'mandant':
             prompt_parts.append("EMPFEÄNGER-KONTEXT: Das Schreiben ist eine Sachstandsinformation an den Mandanten.")
        else:
             prompt_parts.append("EMPFEÄNGER-KONTEXT: Das Schreiben geht an die gegnerische Versicherung/Haftpflicht.")

        if akte_context:
            prompt_parts.append(f"AKTE-KONTEXT:\n{akte_context}")
        if rag_context:
            prompt_parts.append(f"MUSTER-VORLAGEN (zur Orientierung für Struktur/Formulierung):\n{rag_context}")
        
        prompt_parts.append(f"VORGABE / USER-KONTEXT:\n{user_kontext}")
        if notizen:
            prompt_parts.append(f"Besondere Hinweise des Sachbearbeiters:\n{notizen}")

        prompt_parts.append(f"SCHREIBEN-TYP:\n{schreiben_typ or 'Allgemein'}")
        prompt_parts.append("Bitte generiere jetzt den Brieftext (nur Fließtext).")

        prompt = "\n\n".join(prompt_parts)
        
        import asyncio
        full_prompt = f"{system_instruction}\n\n{prompt}"
        loop = asyncio.get_event_loop()
        response_text = await loop.run_in_executor(None, gemini.generate, full_prompt)
        
        return {
            "brief_text": response_text.strip(),
            "schreiben_typ": schreiben_typ or "sonstig"
        }

    async def _sync_frist_zu_calendar(self, akte_id: int, titel: str, datum: str, beschreibung: str = ""):
        """N-G3 Tool Handler: Erstellt ein Google Calendar Event"""
        from app.services.google_calendar_client import google_calendar_client
        import datetime
        
        try:
            parsed_date = datetime.date.fromisoformat(datum)
        except ValueError:
            return {"error": f"Ungültiges Datumsformat: {datum}. Erwartet: YYYY-MM-DD"}
            
        event_id = google_calendar_client.create_event(
            titel=titel,
            datum=parsed_date,
            beschreibung=beschreibung,
            akte_id=akte_id
        )
        
        if event_id:
            return {
                "status": "success",
                "event_id": event_id,
                "datum": datum
            }
        else:
            return {
                "status": "mock",
                "message": "Google Calendar nicht konfiguriert."
            }

    async def _sende_email_an_gegner(self, akte_id: int, betreff: str, text: str, dokument_id: int = None):
        """GM-2 Tool Handler: Sendet eine E-Mail an den Gegner."""
        from app.services.google_gmail_client import google_gmail_client
        
        # 1. Gegner E-Mail aus Akte laden (Wir nutzen den bestehenden /akte_by_id/ API-Pfad 
        #    bzw. passen die Abfrage soweit nötig an. In Aufgabe wurde erwähnt:
        #    'GET /api/ai/query/akte_by_id/?akte_id=...' -> wir nehmen _get)
        try:
            # Versuche Akte per ID zu laden. Wenn der Endpoint noch nicht existiert,
            # fangen wir den Fehler ab und geben einen sauberen Hinweis.
            try:
                akte_data = await self._get("akte_by_id/", {"akte_id": akte_id})
            except Exception as e:
                logger.error(f"Konnte Akte {akte_id} nicht über akte_by_id/ laden: {e}")
                return {"error": f"Informationen zur Akte {akte_id} konnten zur Zeit nicht geladen werden (Endpoint fehlt?)."}
                
            gegner_email = akte_data.get("gegner_email")
            if not gegner_email:
                # Falls keine Email da ist
                return {"error": f"Keine E-Mail-Adresse für den Gegner von Akte {akte_id} hinterlegt."}
                
            erfolg = google_gmail_client.send_email(
                an=gegner_email,
                betreff=betreff,
                text=text
            )
            
            if erfolg:
                return {
                    "status": "success",
                    "an": gegner_email,
                    "betreff": betreff
                }
            elif not google_gmail_client.enabled:
                return {
                    "status": "mock",
                    "message": "Gmail nicht konfiguriert — E-Mail nicht gesendet."
                }
            else:
                 return {"error": "Senden der E-Mail fehlgeschlagen."}
                 
        except Exception as e:
            logger.error(f"Fehler in _sende_email_an_gegner: {e}")
            return {"error": str(e)}

    # -----------------------------------------------------------------------
    # Ergebnis-Formatierung → Frontend-Format
    # -----------------------------------------------------------------------

    def _format_result(self, tool_name: str, raw_data: Any) -> Dict[str, Any]:
        """Wandelt Django-Rohdaten in das Frontend-kompatible Format um."""

        if tool_name == "count_faelle":
            return {
                "status": "ok",
                "result_type": "number",
                "data": raw_data.get("count", 0),
                "label": raw_data.get("label", "Fälle"),
                "query_used": tool_name,
            }

        if tool_name == "erstelle_brief_aus_kontext":
            return {
                "status": "ok",
                "result_type": "brief_aus_kontext",
                "data": raw_data.get("brief_text"),
                "schreiben_typ": raw_data.get("schreiben_typ"),
                "query_used": tool_name,
            }
            
        if tool_name == "sync_frist_zu_calendar":
            if raw_data.get("status") == "success":
                return {
                    "status": "ok",
                    "result_type": "calendar_event_erstellt",
                    "data": {
                        "event_id": raw_data.get("event_id"),
                        "datum": raw_data.get("datum")
                    },
                    "query_used": tool_name,
                }
            elif raw_data.get("status") == "mock":
                return {
                    "status": "ok",
                    "result_type": "info",
                    "data": raw_data.get("message"),
                    "query_used": tool_name,
                }
            else:
                return {
                    "status": "error",
                    "result_type": "text",
                    "data": raw_data.get("error", "Unbekannter Fehler bei Calendar-Sync"),
                    "query_used": tool_name,
                }
                
        if tool_name == "sende_email_an_gegner":
            if raw_data.get("status") == "success":
                return {
                    "status": "ok",
                    "result_type": "email_gesendet",
                    "data": {
                        "an": raw_data.get("an"),
                        "betreff": raw_data.get("betreff")
                    },
                    "query_used": tool_name,
                }
            elif raw_data.get("status") == "mock":
                return {
                    "status": "ok",
                    "result_type": "info",
                    "data": raw_data.get("message"),
                    "query_used": tool_name,
                }
            else:
                 return {
                    "status": "error",
                    "result_type": "fehler",
                    "data": raw_data.get("error", "Konnte E-Mail nicht senden."),
                    "query_used": tool_name,
                }

        if tool_name == "get_akte_by_aktenzeichen":
            akte = raw_data.get("akte")
            if not akte:
                return {
                    "status": "ok",
                    "result_type": "text",
                    "data": "Keine Akte mit diesem Aktenzeichen gefunden.",
                    "query_used": tool_name,
                }
            return {
                "status": "ok",
                "result_type": "table",
                "columns": ["Aktenzeichen", "Mandant", "Gegner", "Status"],
                "data": [[akte["aktenzeichen"], akte["mandant"], akte["gegner"], akte["status"]]],
                "query_used": tool_name,
            }

        if tool_name in ("get_akten_liste", "get_akten_ohne_fragebogen", "get_akten_ohne_dokument", "get_akten_by_gegner"):
            akten = raw_data.get("akten", [])
            rows = [
                [a["aktenzeichen"], a["mandant"], a["gegner"], a["status"], a.get("erstellt_am", "")]
                for a in akten
            ]
            return {
                "status": "ok",
                "result_type": "table",
                "columns": ["Aktenzeichen", "Mandant", "Gegner", "Status", "Erstellt"],
                "data": rows,
                "total": len(rows),
                "query_used": tool_name,
            }

        if tool_name == "get_offene_betraege":
            positionen = raw_data.get("positionen", [])
            rows = [
                [
                    p["akte_az"],
                    p["beschreibung"],
                    f'{p["soll_betrag"]} €',
                    f'{p["haben_betrag"]} €',
                    p["status"],
                ]
                for p in positionen
            ]
            return {
                "status": "ok",
                "result_type": "table",
                "columns": ["Akte", "Beschreibung", "Soll", "Haben", "Status"],
                "data": rows,
                "total": raw_data.get("gesamt_offen", 0),
                "total_label": "Gesamtbetrag offen (€)",
                "query_used": tool_name,
            }

        if tool_name == "get_fristen_naechste_tage":
            fristen = raw_data.get("fristen", [])
            rows = [
                [f["bezeichnung"], f["akte_az"], f["frist_datum"], f.get("prioritaet", "")]
                for f in fristen
            ]
            return {
                "status": "ok",
                "result_type": "table",
                "columns": ["Frist", "Akte", "Fällig am", "Priorität"],
                "data": rows,
                "total": len(rows),
                "query_used": tool_name,
            }

        # Fallback
        return {
            "status": "ok",
            "result_type": "text",
            "data": str(raw_data),
            "query_used": tool_name,
        }

    # -----------------------------------------------------------------------
    # LOKI CHAT — Multi-Turn Function Calling
    # -----------------------------------------------------------------------

    async def _execute_chat_tool(self, tool_name: str, args: dict) -> dict:
        from app.services.hmac_auth import generate_ki_signature
        headers = {"X-KI-Signature": generate_ki_signature()}

        def _safe_json(resp) -> dict:
            """Gibt resp.json() zurück oder einen Fehler-Dict bei HTTP-Fehler / Parse-Fehler."""
            try:
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"_execute_chat_tool HTTP {e.response.status_code} für {tool_name}: {e.response.text[:200]}")
                return {"error": f"Backend-Fehler {e.response.status_code}"}
            except Exception as e:
                logger.error(f"_execute_chat_tool JSON-Parse-Fehler für {tool_name}: {e}")
                return {"error": "Unerwartete Backend-Antwort"}

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                if tool_name == "get_finanzdaten":
                    resp = await client.get(
                        f"{self.django_base}/api/ai/query/finanzdaten/",
                        params={"akte_id": args["akte_id"]},
                        headers=headers
                    )
                    return _safe_json(resp)

                elif tool_name == "erstelle_aufgabe":
                    resp = await client.post(
                        f"{self.django_base}/api/ai/actions/erstelle_aufgabe/",
                        json=args, headers=headers
                    )
                    return _safe_json(resp)

                elif tool_name == "erstelle_frist":
                    resp = await client.post(
                        f"{self.django_base}/api/ai/actions/erstelle_frist/",
                        json=args, headers=headers
                    )
                    return _safe_json(resp)

                elif tool_name == "aendere_aktenstatus":
                    resp = await client.post(
                        f"{self.django_base}/api/ai/actions/aendere_aktenstatus/",
                        json=args, headers=headers
                    )
                    return _safe_json(resp)

                elif tool_name == "get_statistiken":
                    params = {"zeitraum": args.get("zeitraum", "dieser_monat")}
                    if args.get("referent"):
                        params["referent"] = args["referent"]
                    resp = await client.get(
                        f"{self.django_base}/api/ai/query/statistiken/",
                        params=params, headers=headers
                    )
                    return _safe_json(resp)

                elif tool_name == "berechne_rvg":
                    resp = await client.post(
                        f"{self.django_base}/api/ai/actions/berechne_rvg/",
                        json=args, headers=headers
                    )
                    return _safe_json(resp)

                elif tool_name == "entwerfe_brief":
                    stage2 = await self._generate_brief_stage2(
                        akte_id=args["akte_id"],
                        payload=args,
                    )
                    return stage2

                elif tool_name == "erstelle_brief":
                    resp = await client.post(
                        f"{self.django_base}/api/ai/actions/erstelle_brief/",
                        json={
                            "akte_id": args["akte_id"],
                            "brief_text": args.get("brief_text", ""),
                            "betreff": args.get("betreff", ""),
                            "empfaenger": args.get("empfaenger", "versicherung"),
                        },
                        headers=headers
                    )
                    result = _safe_json(resp)
                    if resp.status_code in (200, 201) and "error" not in result:
                        from datetime import datetime as _now_dt
                        datum_mem = _now_dt.now().strftime("%d.%m.%Y")
                        empf_label = "Vers." if args.get("empfaenger", "versicherung") == "versicherung" else "Mdt."
                        betreff_mem = str(args.get("betreff", ""))
                        auszug = str(args.get("brief_text", ""))[0:400]  # type: ignore[index]
                        eintrag = f"Brief an {empf_label} (Betreff: {betreff_mem}): {auszug}"
                        # AUTO ki_memory
                        mem_get = await client.get(
                            f"{self.django_base}/api/cases/akten/{args['akte_id']}/ki_memory/",
                            headers=headers
                        )
                        current_mem = mem_get.json().get("ki_memory", "") if mem_get.status_code == 200 else ""
                        new_mem = f"{current_mem}\n[{datum_mem}] {eintrag}".strip()
                        await client.post(
                            f"{self.django_base}/api/cases/akten/{args['akte_id']}/ki_memory/",
                            json={"ki_memory": new_mem},
                            headers=headers
                        )
                        logger.info(f"AUTO ki_memory Brief für Akte {args['akte_id']}: {eintrag[0:80]}")  # type: ignore[index]
                        # AUTO RAG: Brief als Goldstandard in kanzlei_wissen speichern
                        brief_text_full = str(args.get("brief_text", ""))
                        if len(brief_text_full) > 100:
                            try:
                                from app.services.rag_store import rag_store  # type: ignore[attr-defined]
                                betreff_lower = betreff_mem.lower()
                                if "widerspruch" in betreff_lower:
                                    brief_typ = "widerspruch"
                                elif "erstanschreiben" in betreff_lower or "mandat" in betreff_lower:
                                    brief_typ = "erstanschreiben"
                                elif "sachstand" in betreff_lower or "info" in betreff_lower:
                                    brief_typ = "sachstandsinfo"
                                elif "mahnung" in betreff_lower or "frist" in betreff_lower:
                                    brief_typ = "mahnung"
                                else:
                                    brief_typ = "kanzlei_brief"
                                import time as _time
                                chunk_id = f"brief_{args['akte_id']}_{int(_time.time())}"
                                await rag_store.add_documents(
                                    documents=[brief_text_full],
                                    metadatas=[{
                                        "typ": brief_typ,
                                        "empfaenger": args.get("empfaenger", "versicherung"),
                                        "betreff": betreff_mem,
                                        "akte_id": str(args["akte_id"]),
                                        "datum": datum_mem,
                                    }],
                                    ids=[chunk_id],
                                    collection_name="kanzlei_wissen"
                                )
                                logger.info(f"AUTO RAG: Brief '{betreff_mem}' (Typ: {brief_typ}) in kanzlei_wissen gespeichert.")
                            except Exception as rag_err:
                                logger.warning(f"AUTO RAG Brief-Speicherung fehlgeschlagen (nicht kritisch): {rag_err}")
                    return result

                elif tool_name == "erstelle_zahlungspositionen":
                    resp = await client.post(
                        f"{self.django_base}/api/ai/actions/erstelle_zahlungspositionen/",
                        json={
                            "akte_id": args["akte_id"],
                            "positionen": args.get("positionen", []),
                        },
                        headers=headers
                    )
                    return _safe_json(resp)

                elif tool_name == "deaktiviere_zahlungsposition":
                    resp = await client.post(
                        f"{self.django_base}/api/ai/actions/deaktiviere_zahlungsposition/",
                        json={"zahlungsposition_id": args["zahlungsposition_id"]},
                        headers=headers
                    )
                    return _safe_json(resp)

                elif tool_name == "buche_zahlung":
                    payload = {
                        "zahlungsposition_id": args["zahlungsposition_id"],
                        "haben_betrag": args["haben_betrag"],
                    }
                    if args.get("soll_betrag") is not None:
                        payload["soll_betrag"] = args["soll_betrag"]
                    if args.get("status"):
                        payload["status"] = args["status"]
                    resp = await client.post(
                        f"{self.django_base}/api/ai/actions/buche_zahlung/",
                        json=payload,
                        headers=headers
                    )
                    return _safe_json(resp)

                elif tool_name == "buche_rvg_zahlung":
                    resp = await client.post(
                        f"{self.django_base}/api/ai/actions/buche_rvg_zahlung/",
                        json={"akte_id": args["akte_id"]},
                        headers=headers
                    )
                    return _safe_json(resp)

                elif tool_name == "get_bankbewegungen":
                    resp = await client.get(
                        f"{self.django_base}/api/finance/bankbewegungen/",
                        params={"akte": args["akte_id"], "status": "OFFEN"},
                        headers=headers
                    )
                    return _safe_json(resp)

                elif tool_name == "aktualisiere_zahlungsabgleich":
                    resp = await client.post(
                        f"{self.django_base}/api/ai/actions/aktualisiere_zahlungsabgleich/",
                        json=args,
                        headers=headers
                    )
                    return _safe_json(resp)

                elif tool_name == "aktualisiere_ki_memory":
                    akte_id_mem = args["akte_id"]
                    eintrag = args.get("eintrag", "").strip()
                    # Aktuellen Stand laden und neuen Eintrag anhängen
                    get_resp = await client.get(
                        f"{self.django_base}/api/cases/akten/{akte_id_mem}/ki_memory/",
                        headers=headers
                    )
                    current = get_resp.json().get("ki_memory", "") if get_resp.status_code == 200 else ""
                    from datetime import datetime
                    datum = datetime.now().strftime("%d.%m.%Y")
                    new_memory = f"{current}\n[{datum}] {eintrag}".strip()
                    resp = await client.post(
                        f"{self.django_base}/api/cases/akten/{akte_id_mem}/ki_memory/",
                        json={"ki_memory": new_memory},
                        headers=headers
                    )
                    if resp.status_code in (200, 201):
                        logger.info(f"ki_memory angehängt für Akte {akte_id_mem}: {eintrag[:80]}")
                        return {"status": "gespeichert"}
                    return {"error": f"ki_memory Fehler {resp.status_code}"}

            return {"error": f"Unbekanntes Tool: {tool_name}"}

        except httpx.TimeoutException:
            logger.error(f"_execute_chat_tool Timeout bei Tool: {tool_name}")
            return {"error": f"Timeout bei Ausführung von '{tool_name}' — Backend nicht erreichbar."}
        except Exception as e:
            logger.error(f"_execute_chat_tool unerwarteter Fehler ({tool_name}): {e}", exc_info=True)
            return {"error": f"Interner Fehler bei '{tool_name}': {str(e)}"}

    async def _erkenne_falltyp(self, kontext: dict, ki_memory: str) -> str:
        """
        Bestimmt den Falltyp aus Akten-Kontext.
        Reihenfolge: ki_memory > fragebogen > Gegner/Ziel-Text > Heuristik
        """
        # 1. Bereits im ki_memory gespeichert?
        if ki_memory:
            for line in ki_memory.lower().split("\n"):
                if "falltyp:" in line:
                    return line.split("falltyp:", 1)[-1].strip().split()[0]

        # 2. Fragebogen vorhanden?
        fragebogen = kontext.get("fragebogen", {})
        if isinstance(fragebogen, dict) and fragebogen:
            if fragebogen.get("personenschaden"):
                return "personenschaden"
            # Unfallakte: Unfalldatum oder Kennzeichen vorhanden
            if fragebogen.get("datum_zeit") or fragebogen.get("gegner_kennzeichen"):
                return "verkehrsunfall_haftpflicht"

        # 3. Schlüsselwörter in Ziel/Gegner
        text = f"{kontext.get('ziel', '')} {kontext.get('gegner', '')}".lower()
        if any(w in text for w in ["haftpflicht", "unfall", "versicherung", "schadensregulierung", "stvg", "vvg"]):
            return "verkehrsunfall_haftpflicht"
        if any(w in text for w in ["personenschaden", "schmerzensgeld", "verletzung", "behandlung"]):
            return "personenschaden"

        return "unbekannt"

    async def _lade_workflow_kontext(self, falltyp: str) -> str:
        """
        Lädt das passende Workflow-Dokument aus RAG system_wissen.
        Gibt leeren String zurück wenn kein Treffer oder Fehler.
        """
        if falltyp == "unbekannt":
            return ""
        try:
            from app.services.rag_store import rag_store
            query = f"Workflow Ablauf Stufen {falltyp.replace('_', ' ')}"
            matches = await rag_store.search_similar(
                query_text=query,
                n_results=4,
                filter_dict={"typ": "system_doku"},
                collection_name="system_wissen",
            )
            if not matches:
                return ""
            return "\n---\n".join(m.get("text", m.get("document", "")) for m in matches)
        except Exception as e:
            logger.warning(f"_lade_workflow_kontext Fehler ({falltyp}): {e}")
            return ""

    async def _search_goldstandard_fuer_brief(
        self,
        brief_zweck: str,
        empfaenger: str,
        argumente: list,
        n_results: int = 5,
    ) -> list:
        """
        Dynamischer RAG-Query für Stage-2-Stilvorlagen.
        Baut Query aus brief_zweck + empfaenger + Top-Argument-Thesen.
        Nutzt where-Filter wenn möglich, fällt auf breitere Suche zurück wenn < 3 Treffer.
        """
        from app.services.rag_store import rag_store
        query_parts = [brief_zweck.replace("_", " "), empfaenger]
        for a in (argumente or [])[:2]:
            these = a.get("kern_these", "") if isinstance(a, dict) else ""
            if these:
                query_parts.append(these)
        query = " ".join(query_parts).strip() or "kanzlei brief"

        try:
            matches = await rag_store.search_similar(
                query_text=query,
                n_results=n_results,
                filter_dict={"empfaenger": empfaenger},
                collection_name="kanzlei_wissen",
            )
            if len(matches) < 3:
                matches = await rag_store.search_similar(
                    query_text=query,
                    n_results=n_results,
                    collection_name="kanzlei_wissen",
                )
            return matches or []
        except Exception as e:
            logger.warning(f"_search_goldstandard_fuer_brief Fehler: {e}")
            return []

    async def _generate_brief_stage2(
        self,
        akte_id: int,
        payload: dict,
    ) -> dict:
        """
        Stage 2: Separater, fokussierter Gemini-Call NUR für Brieftext-Formulierung.
        - Eigener schlanker System-Prompt (Kanzlei-Voice + Aufbau + Stilvorlagen)
        - Keine Tools, kein Akten-Volltext, kein Workflow-Kontext
        - Temperatur 1.0 für Formulierungs-Kreativität
        Returns: {"brief_text": str, "betreff_vorschlag": str, "stage2_ok": bool}
        """
        from app.main import get_gemini_client
        gemini = get_gemini_client()
        if not gemini:
            return {
                "brief_text": "",
                "betreff_vorschlag": "",
                "stage2_ok": False,
                "error": "Gemini API nicht bereit",
            }

        brief_zweck = str(payload.get("brief_zweck", "")).strip() or "kanzlei_brief"
        empfaenger = str(payload.get("empfaenger", "versicherung")).strip().lower()
        ton = str(payload.get("ton", "sachlich")).strip().lower()
        fakten = payload.get("fakten", []) or []
        argumente = payload.get("juristische_argumente", []) or []
        forderung = payload.get("forderung") or {}
        besondere_hinweise = str(payload.get("besondere_hinweise", "")).strip()

        # 1. Goldstandard-Stilvorlagen laden (dynamischer Query)
        gs_matches = await self._search_goldstandard_fuer_brief(
            brief_zweck=brief_zweck,
            empfaenger=empfaenger,
            argumente=argumente,
            n_results=5,
        )
        if gs_matches:
            gs_parts = []
            for i, m in enumerate(gs_matches, 1):
                text = (m.get("text") or "").strip()
                meta = m.get("metadata") or {}
                typ = meta.get("typ", "")
                betreff = meta.get("betreff", "")
                label = f"Beispiel {i}" + (f" [{typ}]" if typ else "") + (f" — {betreff}" if betreff else "")
                gs_parts.append(f"--- {label} ---\n{text}")
            goldstandard_block = "\n\n".join(gs_parts)
        else:
            goldstandard_block = "(Keine Stilvorlagen gefunden — orientiere dich strikt am Aufbau oben.)"

        # 2. Fakten-Block
        if fakten:
            fakten_lines = []
            for f in fakten:
                if not isinstance(f, dict):
                    continue
                typ = str(f.get("typ", "?"))
                wert = str(f.get("wert", ""))
                beleg = str(f.get("beleg_dokument_titel", "")).strip()
                line = f"- {typ}: {wert}"
                if beleg:
                    line += f"  [Quelle: {beleg}]"
                fakten_lines.append(line)
            fakten_block = "\n".join(fakten_lines)
        else:
            fakten_block = "(keine expliziten Fakten übergeben)"

        # 3. Argumente-Block
        if argumente:
            arg_lines = []
            for i, a in enumerate(argumente, 1):
                if not isinstance(a, dict):
                    continue
                kt = str(a.get("kern_these", "")).strip()
                bg = str(a.get("begruendung", "")).strip()
                rs = str(a.get("rechtsprechung", "")).strip()
                arg_lines.append(f"{i}. Kern-These: {kt}\n   Begründung: {bg}" + (f"\n   Rechtsprechung: {rs}" if rs else ""))
            argumente_block = "\n\n".join(arg_lines)
        else:
            argumente_block = "(keine juristischen Argumente — reines Erstanschreiben o.ä.)"

        # 4. Forderung-Block
        if forderung and isinstance(forderung, dict):
            f_parts = []
            if forderung.get("betrag_eur") is not None:
                f_parts.append(f"Betrag: {forderung.get('betrag_eur')} EUR")
            if forderung.get("frist_datum"):
                f_parts.append(f"Frist: {forderung.get('frist_datum')}")
            if forderung.get("beschreibung"):
                f_parts.append(f"Beschreibung: {forderung.get('beschreibung')}")
            forderung_block = "\n".join(f_parts) if f_parts else "(keine konkrete Forderung)"
        else:
            forderung_block = "(keine konkrete Forderung)"

        ton_beschreibung = {
            "forsch": "Direkt und bestimmt — klare Forderung, Klagandrohung am Ende, keine Weichmacher.",
            "sachlich": "Neutral und sachlich — keine Eskalation, keine Klagandrohung, Fakten und Forderung klar benennen.",
            "deeskalierend": "Verständnisvoll und konstruktiv — Fokus auf Klärung und Lösung, keine Drohungen, kooperativer Ton.",
        }.get(ton, "Neutral und sachlich.")

        system_prompt = f"""Du bist erfahrener Rechtsanwalt der Kanzlei AWR24 und formulierst einen Brief.
Deine Aufgabe: ein vollständiger, substanzvoller Anwaltsschriftsatz — kein Memo, keine Notiz.

ANWALTLICHER STIL — zwingend:
- Präzise juristische Fachsprache. Keine Memo-Sätze, keine Umgangssprache.
- Nutze die typischen anwaltlichen Formulierungsmuster, z.B.:
  "Wir nehmen Bezug auf...", "Namens und im Auftrag unseres Mandanten...",
  "Soweit Sie meinen, ..., verkennen Sie, dass ...",
  "Wir fordern Sie hiermit auf, ... bis spätestens ...",
  "Die Rechtsprechung ist hier eindeutig: ...",
  "Wir sehen uns daher veranlasst, ...",
  "Für den Fall eines ergebnislosen Fristablaufs behalten wir uns ... ausdrücklich vor"
- Konkrete Rechtsgrundlagen benennen: §§ BGB, StVG, ZPO, einschlägige BGH-/OLG-Entscheidungen
  wenn im Payload oder inhaltlich einschlägig.
- Bei Zahlungserinnerung/Mahnung: Verzug ausdrücklich feststellen (§ 286 BGB), Verzugszinsen
  (§ 288 BGB) benennen, ggf. Mahnkosten und weitere Rechtsverfolgungskosten, Hinweis auf
  gerichtliche Geltendmachung. Bankverbindung NICHT wiederholen — steht im Briefkopf.
- Bei Widerspruch: gegnerische Argumentation konkret aufgreifen und entkräften — keine pauschale
  Zurückweisung. Gutachten, Urteile, Normen zitieren.
- Keine weichen Füllwörter ("eventuell", "möglicherweise", "vielleicht", "sozusagen").
- Keine akademischen Gutachter-Abschnitte ("Sachverhalt:", "Prüfungsmaßstab:", "Ergebnis:", "I.", "II.").

AUFBAU:
1. Eröffnung — präzise Bezugnahme auf Anlass und Datum des Anlasses (Rechnung vom ...,
   Abrechnung vom ..., Ihr Schreiben vom ...). Darf ein oder mehrere Sätze sein, wenn die
   Sache es erfordert (z.B. Abrechnung vom ..., Kürzung um ..., Rechnung vom ... mit
   Fälligkeit am ...). SCHADENNUMMER und AKTENZEICHEN NICHT im Fließtext nennen — stehen
   bereits im Briefkopf aus dem Template.
2. Darstellung und juristische Argumentation — so ausführlich wie die Sache es trägt:
   - Jede Kern-These mit tragender Begründung und (soweit im Payload) Rechtsprechung ausformulieren.
   - Mehrere Argumente nummeriert (1., 2., 3.) — jeweils mehrere Sätze, nicht Halbsatz.
3. Konkrete Forderung — Betrag, Frist, Empfänger. BANKVERBINDUNG/IBAN NICHT nennen —
   steht im Briefkopf aus dem Template.
4. Konsequenzen je nach Ton:
   - forsch: Klagandrohung + Kostenhinweis ("werden wir ohne weitere Vorankündigung gerichtliche
     Schritte einleiten, deren Kosten vollumfänglich zu Ihren Lasten gehen").
   - sachlich: sachliche Ankündigung weiterer Schritte / Verzugsfolgen.
   - deeskalierend: Bitte um kurze Rückäußerung, Terminvorschlag, konstruktive Formulierung.

LÄNGE: folgt der Sache. Ein Widerspruch oder komplexer Schriftsatz soll vollständig ausgearbeitet
sein — nicht künstlich auf wenige Zeilen kürzen. Jede These trägt einen eigenen Absatz mit
mehreren Sätzen. Kurze Zahlungserinnerungen dürfen kurz bleiben, müssen aber Verzug, Zinsen
und Konsequenzen vollständig benennen.

FORMAT:
- NUR Fließtext. Das Template ergänzt automatisch: Briefkopf (Kanzlei-Adresse, Telefon,
  E-Mail, Bankverbindung/BIC), Empfängeranschrift, Datum, Aktenzeichen, Schadennummer,
  Anrede ("Sehr geehrte Damen und Herren,"), Grußformel ("Mit freundlichen Grüßen") und Signatur.
  ALL DAS DARF NICHT im Fließtext stehen — sonst steht es doppelt im fertigen Brief.
- Absätze mit doppelter Leerzeile (\\n\\n) trennen.
- KEIN Markdown (keine Sternchen, keine Rauten, keine Bindestrich-Listen).
- Echte Werte aus FAKTEN nutzen — NIEMALS Platzhalter wie [Datum] oder [Betrag].

TON: {ton_beschreibung}

VERBOTEN:
- Wörtliche Copy-Pastes aus den Argument-Feldern — immer anwaltlich ausformulieren.
- Fakten erfinden, die nicht im Payload oder in den Stilvorlagen stehen.
- Personalisierte Anrede ("Herr Müller") — kommt aus dem Template.
- NbLM-Abschnittstitel übernehmen ("GUTACHTERLICHE STELLUNGNAHME", "Prüfungsmaßstab").
- Kurze memoartige Halbsatz-Antworten — es muss ein vollwertiger Schriftsatz sein.

STILVORLAGEN — VERBINDLICHE REFERENZ (echte Kanzlei-Briefe):
Orientiere dich ENG an Ton, Satzbau, Länge und anwaltlichen Formulierungsmustern dieser Briefe.
Übernimm typische Satzkonstruktionen und anwaltliche Phrasen und passe sie an die neuen Fakten an.
NICHT die konkreten Sachverhalte/Namen/Beträge kopieren — NUR Stil und Struktur.

{goldstandard_block}

---

PAYLOAD FÜR DIESEN BRIEF:

Brief-Zweck: {brief_zweck}
Empfänger: {empfaenger}
Ton: {ton}

FAKTEN (ausschließlich diese verwenden):
{fakten_block}

JURISTISCHE ARGUMENTE:
{argumente_block}

FORDERUNG:
{forderung_block}

BESONDERE HINWEISE:
{besondere_hinweise if besondere_hinweise else "(keine)"}

---

ANTWORT-FORMAT — PFLICHT, NICHTS ABWEICHEN:

BETREFF: <prägnante Betreffzeile, maximal 80 Zeichen, OHNE Aktenzeichen>
---
<Fließtext des Briefes>

Beginne jetzt mit "BETREFF:"."""

        from google.genai import types as genai_types
        config = genai_types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=1.0,
            thinking_config=genai_types.ThinkingConfig(include_thoughts=False),
        )

        try:
            response = await gemini.client.aio.models.generate_content(
                model=gemini.model_name,
                contents=[{"role": "user", "parts": [{"text": "Schreibe jetzt den Brief."}]}],
                config=config,
            )
        except Exception as e:
            err_str = str(e)
            logger.error(f"Stage 2 Gemini-Call fehlgeschlagen: {err_str}")
            if "429" in err_str or "ResourceExhausted" in err_str or "quota" in err_str.lower():
                return {
                    "brief_text": "",
                    "betreff_vorschlag": "",
                    "stage2_ok": False,
                    "error": "Gemini API Tageslimit erreicht.",
                }
            return {
                "brief_text": "",
                "betreff_vorschlag": "",
                "stage2_ok": False,
                "error": f"Stage-2-Call fehlgeschlagen: {err_str[:200]}",
            }

        try:
            raw_text = response.text if response.candidates else ""
        except ValueError:
            raw_text = ""

        raw_text = _strip_markdown(raw_text or "").strip()
        if not raw_text:
            return {
                "brief_text": "",
                "betreff_vorschlag": "",
                "stage2_ok": False,
                "error": "Stage 2 lieferte leeren Text zurück.",
            }

        # BETREFF: <zeile>\n---\n<brief_text> parsen
        betreff_vorschlag = ""
        brief_text = raw_text
        lines = raw_text.split("\n", 1)
        if lines and lines[0].upper().startswith("BETREFF:"):
            betreff_vorschlag = lines[0].split(":", 1)[1].strip() if ":" in lines[0] else ""
            rest = lines[1] if len(lines) > 1 else ""
            # Trenner "---" wegschneiden
            parts = rest.split("---", 1)
            brief_text = (parts[1] if len(parts) > 1 else parts[0]).strip()

        logger.info(
            f"Stage 2: Brief generiert (akte={akte_id}, zweck={brief_zweck}, empf={empfaenger}, "
            f"ton={ton}, wortzahl={len(brief_text.split())}, gs_matches={len(gs_matches)})"
        )

        return {
            "brief_text": brief_text,
            "betreff_vorschlag": betreff_vorschlag,
            "stage2_ok": True,
            "goldstandard_count": len(gs_matches),
        }

    async def match_bankbewegungen(
        self,
        bankbewegungen: list[dict],
        offene_forderungen: list[dict],
        akten_index: list[dict],
    ) -> dict:
        """
        Loki Bank-Matching (Task: LOKI_BANK_MATCHING).

        Nimmt offene Bankbewegungen + offene Zahlungsabgleiche + Akten-Index und
        liefert strukturierte Match-Vorschläge (Bewegung → Forderung) mit
        Confidence + Begründung zurück. KEIN Auto-Apply — Backend gibt die
        Vorschläge ans Frontend, User bestätigt.

        Strategie (im Prompt):
          1. Aktenzeichen-Match im Verwendungszweck (höchste Confidence)
          2. AZ + Betrag teilweise → Teilzahlung
          3. Mandantenname-Match + Betrag-Match
          4. Reiner Betrags-Match → sehr niedrige Confidence
          5. Negativbetrag (Ausgang) → nur vorschlagen wenn plausibel

        temperature=0.1 (deterministisch, keine Kreativität nötig)
        """
        import json as _json
        from app.main import get_gemini_client
        gemini = get_gemini_client()
        if not gemini:
            return {
                "status": "error",
                "error": "KI-Dienst nicht bereit.",
                "vorschlaege": [],
                "gesamt_analysiert": 0,
                "gesamt_vorgeschlagen": 0,
                "gesamt_unklar": 0,
            }

        if not bankbewegungen:
            return {
                "status": "ok",
                "vorschlaege": [],
                "gesamt_analysiert": 0,
                "gesamt_vorgeschlagen": 0,
                "gesamt_unklar": 0,
            }

        # Kompaktes JSON-Paket aufbauen (nur relevante Felder, keine NoneNamen)
        paket = {
            "bankbewegungen": bankbewegungen,
            "offene_forderungen": offene_forderungen,
            "akten_index": akten_index,
        }
        paket_json = _json.dumps(paket, ensure_ascii=False, default=str)

        system_prompt = """Du bist ein präziser Buchhaltungs-Assistent einer Rechtsanwaltskanzlei.
Deine Aufgabe: Bankbewegungen (CSV-Zeilen aus einem Kontoauszug) den offenen
Forderungen (Zahlungsabgleiche von Akten) zuordnen.

MATCHING-REGELN — strikt in dieser Reihenfolge prüfen:

1) AKTENZEICHEN-MATCH (höchste Priorität, confidence 0.9–0.98)
   Regex: \\b\\d{1,3}\\.\\d{2}\\.[A-Za-z]{2,4}\\b (z.B. "17.26.awr", "8.25.awr")
   - AZ exakt im Verwendungszweck UND Betrag matcht Soll-Betrag einer Position der Akte
     → confidence 0.95–0.98
   - AZ exakt, aber Betrag weicht ab (Teilzahlung möglich)
     → confidence 0.75–0.85, reason erwähnt "Teilzahlung" oder "Betrag abweichend"

2) MANDANTENNAME-MATCH (confidence 0.7–0.85)
   - Kein AZ im Verwendungszweck, aber "auftraggeber" enthält Mandantennamen
     einer Akte aus akten_index UND Betrag matcht eine Position der Akte
     → confidence 0.75–0.85

3) NUR BETRAGS-MATCH (confidence < 0.5)
   - Keinerlei eindeutige Kennung, nur Betrag gleich → confidence ≤ 0.4
   - Lieber zahlungsabgleich_id = null und "unklar" melden

4) NEGATIVBETRAG (Ausgang, betrag < 0)
   - Nur wenn plausibel eine Weiterleitung an Mandant (z.B. Auszahlung)
     einer Akte zugeordnet werden kann → sonst zahlungsabgleich_id = null
   - Standardmäßig confidence ≤ 0.5 für Ausgänge

ABSOLUT VERBOTEN:
- Keine erfundenen zahlungsabgleich_ids — nur IDs aus "offene_forderungen" verwenden.
- Kein Match aus Bauchgefühl. Bei Unsicherheit: zahlungsabgleich_id = null,
  confidence = 0.0, reason = kurze Begründung warum unklar.
- Keine Zuordnung derselben zahlungsabgleich_id an mehrere Bankbewegungen
  (außer Teilzahlungen mit expliziter Begründung).

ANTWORT-FORMAT — NUR valides JSON, KEIN Markdown, KEINE Erklärung drumherum:

{
  "vorschlaege": [
    {
      "bankbewegung_id": 5,
      "zahlungsabgleich_id": 12,
      "confidence": 0.95,
      "reason": "AZ 17.26.awr im Verwendungszweck + Betrag 1300€ matcht Position 'Wertminderung' exakt"
    },
    {
      "bankbewegung_id": 7,
      "zahlungsabgleich_id": null,
      "confidence": 0.0,
      "reason": "Kein AZ, Auftraggeber 'Klaus-Peter Pehr' nicht in Mandanten-Liste — kein Mandantenfall"
    }
  ]
}

Für JEDE Bankbewegung aus dem Input MUSS genau ein Eintrag im Array vorkommen
(auch wenn zahlungsabgleich_id = null)."""

        user_prompt = f"""INPUT-DATEN:

{paket_json}

Analysiere JETZT und liefere das JSON-Array der Vorschläge."""

        from google.genai import types as genai_types
        config = genai_types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.1,
            response_mime_type="application/json",
            thinking_config=genai_types.ThinkingConfig(include_thoughts=False),
        )

        try:
            response = await gemini.client.aio.models.generate_content(
                model=gemini.model_name,
                contents=[{"role": "user", "parts": [{"text": user_prompt}]}],
                config=config,
            )
        except Exception as e:
            err_str = str(e)
            logger.error(f"match_bankbewegungen Gemini-Call fehlgeschlagen: {err_str}")
            return {
                "status": "error",
                "error": f"Gemini-Call fehlgeschlagen: {err_str[:200]}",
                "vorschlaege": [],
                "gesamt_analysiert": len(bankbewegungen),
                "gesamt_vorgeschlagen": 0,
                "gesamt_unklar": 0,
            }

        try:
            raw_text = (response.text or "").strip()
        except Exception:
            raw_text = ""

        if not raw_text:
            return {
                "status": "error",
                "error": "Leere Antwort von Gemini.",
                "vorschlaege": [],
                "gesamt_analysiert": len(bankbewegungen),
                "gesamt_vorgeschlagen": 0,
                "gesamt_unklar": 0,
            }

        # Markdown-Wrapper abschneiden falls Gemini es doch zurückgibt
        if raw_text.startswith("```"):
            raw_text = raw_text.strip("`")
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
            raw_text = raw_text.strip()

        try:
            parsed = _json.loads(raw_text)
        except Exception as e:
            logger.error(f"match_bankbewegungen JSON-Parse fehlgeschlagen: {e} | Raw: {raw_text[:300]}")
            return {
                "status": "error",
                "error": f"Antwort nicht als JSON parsbar: {str(e)[:200]}",
                "vorschlaege": [],
                "gesamt_analysiert": len(bankbewegungen),
                "gesamt_vorgeschlagen": 0,
                "gesamt_unklar": 0,
            }

        raw_vorschlaege = parsed.get("vorschlaege") if isinstance(parsed, dict) else parsed
        if not isinstance(raw_vorschlaege, list):
            return {
                "status": "error",
                "error": "Gemini-Antwort enthält kein 'vorschlaege' Array.",
                "vorschlaege": [],
                "gesamt_analysiert": len(bankbewegungen),
                "gesamt_vorgeschlagen": 0,
                "gesamt_unklar": 0,
            }

        # Validieren: IDs gegen Input prüfen, Halluzinationen rausfiltern
        gueltige_bew_ids = {int(b.get("id")) for b in bankbewegungen if b.get("id") is not None}
        gueltige_abg_ids = {int(f.get("zahlungsabgleich_id")) for f in offene_forderungen if f.get("zahlungsabgleich_id") is not None}

        geprueft: list[dict] = []
        for v in raw_vorschlaege:
            if not isinstance(v, dict):
                continue
            try:
                bew_id = int(v.get("bankbewegung_id"))
            except Exception:
                continue
            if bew_id not in gueltige_bew_ids:
                continue

            abg_id_raw = v.get("zahlungsabgleich_id")
            if abg_id_raw is None:
                abg_id = None
            else:
                try:
                    abg_id_int = int(abg_id_raw)
                    abg_id = abg_id_int if abg_id_int in gueltige_abg_ids else None
                except Exception:
                    abg_id = None

            try:
                conf = float(v.get("confidence", 0.0))
            except Exception:
                conf = 0.0
            conf = max(0.0, min(1.0, conf))
            if abg_id is None:
                conf = min(conf, 0.5)

            reason = str(v.get("reason", "")).strip()[:500]

            geprueft.append({
                "bankbewegung_id": bew_id,
                "zahlungsabgleich_id": abg_id,
                "confidence": round(conf, 3),
                "reason": reason,
            })

        vorgeschlagen = sum(1 for v in geprueft if v["zahlungsabgleich_id"] is not None)
        unklar = sum(1 for v in geprueft if v["zahlungsabgleich_id"] is None)

        logger.info(
            f"match_bankbewegungen: analysiert={len(bankbewegungen)}, "
            f"vorgeschlagen={vorgeschlagen}, unklar={unklar}"
        )

        return {
            "status": "ok",
            "vorschlaege": geprueft,
            "gesamt_analysiert": len(bankbewegungen),
            "gesamt_vorgeschlagen": vorgeschlagen,
            "gesamt_unklar": unklar,
        }

    async def handle_akte_chat(
        self,
        akte_id: int,
        messages: list[dict],
        kontext: dict,
        ki_memory: str = "",
        active_tab: str = "ki",
    ) -> dict:
        from app.main import get_gemini_client
        gemini = get_gemini_client()
        if not gemini:
            return {"reply": "Gemini API nicht bereit", "actions_taken": []}

        # Finanzdaten lesbar formatieren
        finanzdaten_raw = kontext.get('finanzdaten', [])
        if finanzdaten_raw:
            gesamt_soll = sum(p.get('soll', 0) for p in finanzdaten_raw)
            gesamt_haben = sum(p.get('haben', 0) for p in finanzdaten_raw)
            fd_lines = []
            for p in finanzdaten_raw:
                zp_id = p.get('id', '?')
                cat = p.get('category', '–')
                beschr = p.get('beschreibung', '–')
                soll = p.get('soll', 0)
                haben = p.get('haben', 0)
                st = p.get('status', '–')
                fd_lines.append(f"  [ID:{zp_id}][{cat}] {beschr}: Forderung={soll:.2f}€, Erhalten={haben:.2f}€, Status={st}")
            fd_lines.append(f"  → GESAMT: Forderung={gesamt_soll:.2f}€, Erhalten={gesamt_haben:.2f}€, Noch offen={gesamt_soll - gesamt_haben:.2f}€")
            finanzdaten_text = "\n".join(fd_lines)
        else:
            finanzdaten_text = "Keine Finanzdaten vorhanden."

        # Aufgaben lesbar formatieren
        aufgaben_raw = kontext.get('aufgaben', [])
        aufgaben_text = "\n".join(
            f"  - {a.get('titel', '?')} (Status: {a.get('status', '?')}, Fällig: {a.get('faellig_am', 'k.A.')})"
            for a in aufgaben_raw
        ) if aufgaben_raw else "Keine offenen Aufgaben."

        # Fristen lesbar formatieren
        fristen_raw = kontext.get('fristen', [])
        fristen_text = "\n".join(
            f"  - {f.get('bezeichnung', '?')} am {f.get('frist_datum', '?')} [Priorität: {f.get('prioritaet', '?')}, Erledigt: {f.get('erledigt', False)}]"
            for f in fristen_raw
        ) if fristen_raw else "Keine Fristen vorhanden."

        # Dokumente lesbar formatieren
        dokumente_raw = kontext.get('dokumente', [])
        dokumente_text = "\n".join(
            f"  - [{d.get('kategorie', '–')}] {d.get('titel', '?')} (Datum: {d.get('datum', 'k.A.')})"
            for d in dokumente_raw
        ) if dokumente_raw else "Keine Dokumente vorhanden."

        # Generierte Briefe (KI-erstellte Schreiben) mit Inhalt-Snippet
        gen_docs_raw = kontext.get('generierte_dokumente', [])
        if gen_docs_raw:
            gen_docs_lines = []
            for gd in gen_docs_raw:
                raw_snippet = gd.get('inhalt_snippet') or ''
                snippet = str(raw_snippet).strip()
                kurz = snippet[0:400]  # type: ignore[index]
                zeile = f"  [{gd.get('typ', '–')}] {gd.get('betreff', '?')} ({gd.get('erstellt_am', 'k.A.')})"
                if kurz:
                    zeile += f"\n    Inhalt: {kurz}..."
                gen_docs_lines.append(zeile)
            gen_docs_text = "\n".join(gen_docs_lines)
        else:
            gen_docs_text = "Noch keine KI-generierten Briefe vorhanden."

        # Gegenstandswert aus Finanzdaten berechnen (Summe aller Soll-Beträge)
        gegenstandswert = sum(p.get('soll', 0) for p in finanzdaten_raw)

        # Stage-Detection: Falltyp erkennen + Workflow aus RAG laden
        falltyp = await self._erkenne_falltyp(kontext, ki_memory)
        workflow_kontext = await self._lade_workflow_kontext(falltyp)

        # IBAN-Status für Loki (Fakt aus DB, kein Raten)
        iban_hinterlegt = bool(kontext.get('mandant_bankverbindung', '').strip())

        from datetime import datetime as _dt
        heute_str = _dt.now().strftime("%d.%m.%Y")

        # Goldstandard-Stilvorlagen werden NICHT in Stage 1 geladen — Stage 2 (entwerfe_brief) holt sie
        # sich dynamisch per _search_goldstandard_fuer_brief anhand des Brief-Zwecks.

        # RAG: ALLE Dokument-Inhalte dieser Akte laden — vollständig, wie Anwalt der Akte liest
        akte_rag_text = ""
        try:
            from app.services.rag_store import rag_store  # type: ignore[attr-defined]
            alle_chunks = rag_store.get_alle_akte_chunks(akte_id)
            if alle_chunks:
                chunk_parts = []
                aktueller_titel = None
                for chunk in alle_chunks:
                    meta = chunk.get("metadata", {})
                    titel_c = meta.get("titel", "?")
                    kat_c = meta.get("kategorie", "?")
                    if titel_c != aktueller_titel:
                        chunk_parts.append(f"\n[{kat_c}: {titel_c}]")
                        aktueller_titel = titel_c
                    chunk_parts.append(str(chunk.get("text", "")))  # type: ignore[arg-type]
                akte_rag_text = "\n".join(chunk_parts).strip()
                logger.info(f"handle_akte_chat: {len(alle_chunks)} Chunks (vollständig) für Akte {akte_id} geladen.")
        except Exception as _rag_err:
            logger.warning(f"akte_dokumente Vollladung fehlgeschlagen (akte_id={akte_id}): {_rag_err}")

        system_prompt = f"""Du bist Loki, der KI-Assistent der Kanzlei AWR24. Du hast VOLLSTÄNDIGEN Zugriff auf folgende Akte:

HEUTIGES DATUM: {heute_str} — nutze dieses Datum als Basis für alle Fristen und Aufgaben!
AKTE-ID (für Tool-Aufrufe): {akte_id}
AKTENZEICHEN: {kontext.get('aktenzeichen', '')}
MANDANT: {kontext.get('mandant', '')}
GEGNER/VERSICHERUNG: {kontext.get('gegner', '')}
ZIEL/MANDAT: {kontext.get('ziel', 'Nicht angegeben')}
STATUS: {kontext.get('status', '')}
GEGENSTANDSWERT (Summe Soll-Beträge Finanzen): {gegenstandswert:.2f} €

FINANZDATEN (bereits vollständig geladen):
{finanzdaten_text}

DOKUMENTE IN DER AKTE (hochgeladene Dateien, Scans — Metadaten):
{dokumente_text}

KANZLEI-ABKÜRZUNGEN (in Dokumenttiteln und Texten — verbindlich für die gesamte Akte):
Mdt. / MDT  = Mandant          |  Vers. / VERS  = Versicherung / Gegner
SV          = Sachverständiger  |  GA            = Gutachten
VM          = Vollmacht         |  VN            = Versicherungsnehmer
VU          = Verkehrsunfall    |  STA           = Staatsanwaltschaft / Staatsanwalt
ZM          = Zahlungsmitteilung / Zahlungsaufforderung
GDV         = Gesamtverband der Deutschen Versicherungswirtschaft (Branchenverband)
DS          = Deckungsschutz    |  RG            = Regulierung
RW          = Restwert          |  AN            = Anforderung
KZ          = Kennzeichen       |  AZ            = Aktenzeichen
REP         = Reparatur         |  NU            = Nutzungsausfall
AWR24       = Kanzlei (RA Winter, Aktenzeichen-Präfix)
Erstanschr. = Erstanschreiben   |  Bestät.       = Bestätigung

DOKUMENT-INHALTE (VOLLSTÄNDIGER Akteninhalt — alle indexierten Dokumente dieser Akte):
{akte_rag_text if akte_rag_text else "⚠️ KEINE DOKUMENTE INDEXIERT — Du hast KEINEN Zugriff auf Dokumenteninhalte. NIEMALS behaupten Dokumente lesen zu können. NIEMALS Inhalte erfinden oder vermuten."}

GENERIERTE BRIEFE (durch Loki erstellte Schreiben — Inhalt vollständig lesbar):
{gen_docs_text}

VERSAND-STATUS (WICHTIG — lies diese Regeln VOR jeder Handlungsempfehlung):
- Ein Dokument in "DOKUMENTE IN DER AKTE" mit Titel "E-Mail: ..." bedeutet: dieser Brief wurde bereits per E-Mail VERSENDET.
  → NIEMALS "Erstanschreiben versenden" empfehlen wenn bereits ein E-Mail-Dokument vorhanden ist.
- Ein generierter Brief (in GENERIERTE BRIEFE) an "versicherung" = Erstanschreiben Versicherung wurde erstellt (Stufe 2A erledigt).
- Wenn Erstanschreiben Versicherung erstellt UND E-Mail-Dokument vorhanden → Brief wurde versendet.
  → Nächster Schritt: Erstanschreiben an MANDANTEN (Stufe 2B) vorschlagen.
- Wenn BEIDE Briefe vorhanden (Versicherung + Mandant) → Nächster Schritt: Aufgabe "Antwort Versicherung abwarten — Frist 14 Tage" erstellen.
- Wenn generierter Brief an "mandant" vorhanden → Stufe 2B erledigt.

OFFENE AUFGABEN:
{aufgaben_text}

FRISTEN:
{fristen_text}

FRAGEBOGEN-DATEN:
{kontext.get('fragebogen', {})}

KI-MEMORY (Fakten aus früheren Sessions — NUR lesen, nie erfinden):
{ki_memory if ki_memory else "Noch keine Einträge."}

⚠️ ABSOLUTE GRUNDREGEL — KEINE AUSNAHMEN:
NIEMALS Wissenslücken mit Vermutungen füllen. NUR bestätigte Fakten aus den obigen Daten verwenden.
Wenn Information fehlt: klar sagen "Diese Information liegt mir nicht vor."
NIEMALS Dokumenteninhalte erfinden, raten oder aus dem Kontext erschließen wenn kein Dokumentinhalt oben steht.
NIEMALS behaupten etwas sehen/lesen zu können was nicht in DOKUMENT-INHALTE steht.

ERKANNTER FALLTYP: {falltyp}

WORKFLOW-WISSEN FÜR DIESEN FALLTYP:
{workflow_kontext if workflow_kontext else "Kein spezifischer Workflow bekannt — allgemeine Unterstützung aktiv. Falls Falltyp unklar: User freundlich fragen welcher Rechtsbereich (Verkehrsunfall, Mietrecht, Arbeitsrecht etc.)."}

MANDANT IBAN/BANKVERBINDUNG IN DB: {"Ja, hinterlegt" if iban_hinterlegt else "NEIN — noch nicht eingetragen (wird für Auszahlungen benötigt)"}

AKTIVER TAB: {active_tab}
{_tab_hinweis(active_tab)}

WICHTIGE REGELN:
- ABSOLUTES MARKDOWN-VERBOT: Verwende in KEINER Antwort Markdown-Formatierung. Weder **Fettschrift**, noch *Kursivschrift*, noch ## Überschriften, noch - Aufzählungszeichen, noch 1. nummerierte Listen mit Sternchen oder Rauten. Schreibe ausschließlich in normalem Fließtext mit Absätzen. Wenn du Punkte aufzählen willst, schreibe sie als Satz oder mit Ziffern ohne Sternchen.
- Die AKTE-ID für alle Tool-Aufrufe ist: {akte_id} — verwende sie DIREKT, frage den User NIEMALS danach.
- KI-MEMORY nach jeder bestätigten Aktion mit `aktualisiere_ki_memory` aktualisieren.
- Nach Brief-Erstellung (`erstelle_brief`): Speichere SOFORT in ki_memory: Datum + Empfänger + Betreff + die ersten 400 Zeichen des Brieftextes. Beispiel: "[26.03.2026] Erstanschreiben Vers. (Betreff: Schadensregulierung): Hiermit zeigen wir an, dass wir Herrn Kalaycioglu in der obengenannten Angelegenheit mandatiert wurden..."
- WICHTIG: Falls `aktualisiere_ki_memory` fehlschlägt — dem User NIEMALS davon berichten. Einfach schweigend übergehen. Der User interessiert sich nicht für interne Speichervorgänge.
- Wenn Falltyp erkannt und NICHT im KI-MEMORY: beim ersten Chat-Aufruf EINMALIG speichern: aktualisiere_ki_memory mit "Falltyp: {falltyp}".
- Wenn User fragt "Was soll ich als nächstes tun?" oder ähnliches: Antwort aus WORKFLOW-WISSEN oben ableiten und aktuelle Stufe anhand Dokumente/Aufgaben/KI-MEMORY bestimmen.
- WORKFLOW-LÜCKEN EIGENANALYSE: Leite Lücken SELBST aus den DOKUMENT-INHALTEN und der Dokumentliste ab — nicht aus Titeln raten! Nutze dazu die KANZLEI-ABKÜRZUNGEN. Beispiel: Gibt es ein Schreiben an Vers. aber keines an Mdt.? Wurde nach IBAN gefragt? Liegt eine Vollmacht vor? Weise den User aktiv auf echte Lücken hin — aber nur wenn du sie durch Inhaltslesen BELEGEN kannst.
- IBAN: Wenn "MANDANT IBAN" oben "NEIN" zeigt: weise aktiv darauf hin, dass die IBAN noch nicht in den Stammdaten hinterlegt ist.
- Du hast ALLE Finanzdaten, Dokumente und Aufgaben oben vollständig — nutze sie direkt aus dem Kontext.
- Frage NIEMALS nach Daten, die bereits im obigen Kontext stehen.
- GEGENSTANDSWERT für RVG = Summe der Soll-Beträge in den Finanzdaten (oben ausgewiesen). Wenn dieser Wert 0 oder sehr niedrig ist (z.B. nur Kostenpauschale), weise den User darauf hin, dass zuerst die Schadenspositionen (Reparatur, Gutachten etc.) eingetragen werden sollten, bevor RVG sinnvoll berechnet werden kann.
- Antworte immer auf Deutsch, präzise und kanzlei-professionell.

DOKUMENT-ZITIERGEBOT (GILT FÜR ALLE ANTWORTEN):
Du hast die vollständigen Dokument-Inhalte der Akte oben im Kontext. Nutze sie aktiv:

1. Bei Aussagen über Beträge, Daten, Personen, Kennzeichen, Schadenpositionen:
   Nenne IMMER das Quelldokument. Beispiel: "Laut 'SV-Rechnung' vom 05.01.2026 beträgt das
   Sachverständigenhonorar 999,34€." — nicht einfach "der Betrag ist 999,34€".

2. Bei Rückfragen und Vorschlägen ("Soll ich X tun?"):
   Begründe IMMER mit Dokumentbezug. Beispiel: "Im Versicherungsschreiben vom 12.03.2026 steht,
   dass die Reparaturkosten anerkannt wurden — soll ich das jetzt buchen?"

3. Bei Widersprüchen zwischen Finanzdaten und Dokumenten:
   Zitiere konkret: "Im Finanz-Tab steht SOLL=500€, aber die 'SV-Rechnung' nennt 999,34€."

4. Bei Workflow-Vorschlägen:
   Stütze dich auf Dokument-Inhalte: "Das Versicherungsschreiben enthält keine Aussage zu den
   RVG-Gebühren — diese müssen wir noch gesondert fordern."

Ziel: Der User soll sofort wissen WOHER die Information stammt, ohne die gesamte Akte
durchsuchen zu müssen. Immer Dokumenttitel nennen, nie nur "laut Akte" oder "ich sehe".

BRIEFE — NEUER ZWEI-STUFEN-ABLAUF (PFLICHT, GILT FÜR JEDEN BRIEF EINZELN):

ABSOLUTE GRUNDREGEL: Du schreibst NIEMALS Brief-Fließtext direkt in deine Chat-Antwort.
Für JEDEN Brief: rufe `entwerfe_brief` auf. Stage 2 formuliert den Brief, du präsentierst ihn nur.

Schritt 1 — Fakten und Argumente sammeln, entwerfe_brief aufrufen:
  1. Kuratiere aus DOKUMENT-INHALTE oben die konkret belegbaren Fakten (Datum, Beträge,
     Positionen, Beleg-Dokumente). Nur belegbare Fakten — keine Vermutungen.
  2. Bei NotebookLM-Input (siehe NOTEBOOKLM-WORKFLOW unten): extrahiere Kern-Thesen
     strukturiert in das juristische_argumente-Array.
  3. Schlage anhand Kontext einen Ton vor: "forsch" (Mahnung, zweiter Widerspruch),
     "sachlich" (Erstanschreiben, Sachstandsinfo), "deeskalierend" (Mandantenschreiben).
  4. Rufe `entwerfe_brief` mit akte_id, brief_zweck, empfaenger, ton, fakten,
     juristische_argumente, optional forderung und besondere_hinweise.
  5. Stage 2 liefert brief_text und betreff_vorschlag zurück.
  6. Zeige den zurückgegebenen brief_text 1:1 im Chat — KEINE Umformulierung.
     Schließe mit: "Soll ich diesen Brief so speichern? (Ja / Nein oder Änderungswunsch)"

Schritt 2 — Speichern nach Bestätigung:
  ⚡ SONDERREGEL: Wenn der User exakt "%%BRIEF_SPEICHERN%%" sendet → Klick auf Speichern-Button.
  → SOFORT `erstelle_brief` mit dem Entwurf-Text von Stage 2 aufrufen. KEIN Text davor.
  Wenn der User anders bestätigt ("Ja", "Speichern", "Ok", "Mach das" o.ä.):
  → Rufe SOFORT `erstelle_brief` mit brief_text und betreff aus dem Stage-2-Resultat auf.
  Falls der User Änderungen wünscht: rufe `entwerfe_brief` erneut mit angepasstem Payload auf
  (z.B. anderer ton, zusätzliche Fakten, überarbeitete Argumente) → zeige neuen Entwurf.
  NIEMALS `erstelle_brief` ohne ausdrückliche Bestätigung aufrufen.
  NIEMALS mehrere Briefe gleichzeitig — immer einen nach dem anderen.
  Beim Doppelpack: erst Versicherungsbrief entwerfen → bestätigen → speichern → dann Mandantenbrief.

AUSNAHME — RVG-FINALSCHREIBEN:
`berechne_rvg` liefert einen rechtlich geprüften `brief_text_vorlage` + `betreff_vorlage` zurück.
Diese Felder gehen NICHT durch entwerfe_brief — nimm sie 1:1 und rufe direkt erstelle_brief auf
(brief_text = brief_text_vorlage, betreff = betreff_vorlage). KEINE Umformulierung, KEINE Stage 2.

NOTEBOOKLM-WORKFLOW (täglich genutzt):

Phase 1 — Du generierst den NotebookLM-Prompt:
  Der User fordert eine juristische Analyse an. Du erzeugst einen strukturierten Prompt
  (Sachverhalt, Rechtsfragen, Ziel) — der User kopiert ihn in NotebookLM.

  !!DATENSCHUTZ-PFLICHT (DSGVO) — GILT FÜR ALLE PROMPTS FÜR EXTERNE KI-TOOLS!!
  NIEMALS echte Namen, Kennzeichen, Nummern oder personenbezogene Daten einbauen.
  Mandantenname → "unser Mandant"; Gegner → "die Versicherung"; Kennzeichen, Aktenzeichen,
  SV-Namen, Adressen → weglassen. Sachliche Angaben (Beträge, Zeiträume, Fahrzeugtyp,
  rechtliche Situation) dürfen bleiben.

Phase 2 — NotebookLM liefert Gutachter-Sprache:
  Akademische Überschriften, Nummerierung I./II., "GUTACHTERLICHE STELLUNGNAHME" etc. —
  das ist NbLM-Sprache, keine Kanzlei-Sprache.

Phase 3 — User fügt die NbLM-Analyse bei dir ein:
  Erkenne den Text an Überschriften / Nummerierung / Gutachter-Sprache.
  Antworte knapp: "Das ist die NotebookLM-Analyse — ich extrahiere die Kern-Argumente und
  entwerfe den Brief."
  EXTRAHIERE pro Argument STRUKTURIERT in das juristische_argumente-Array:
    - kern_these: Ein-Satz-These (KEINE Gutachter-Überschrift wie "Vorrang der individuellen Begutachtung")
    - begruendung: 2-3 Sätze Klartext (kein "Prüfungsmaßstab:", kein "Ergebnis:")
    - rechtsprechung: optional, falls im Text vorhanden
  VERGISS die NbLM-Überschriften und die akademische Struktur.
  Rufe dann `entwerfe_brief` mit diesem Array + Fakten aus der Akte auf.
  Stage 2 formuliert daraus den kurzen, direkten Anwaltsbrief — nicht du.

- Wenn der User einen Brief mit RVG-Gebühren anfordert:
  1. Prüfe ob FINANZDATEN bereits RVG-Positionen enthalten.
  2. Falls keine: Nutze zuerst `berechne_rvg` (erstellt Positionen + Finalschreiben-Text).
  3. Danach greift die RVG-Finalschreiben-Ausnahme oben — KEIN entwerfe_brief nötig.
- Die RVG-Gebühren werden automatisch aus dem Gegenstandswert berechnet — frage nicht danach.

SCHÄTZPOSITION DURCH TATSÄCHLICHE RECHNUNG ERSETZEN:
Wenn eine Position auf einem SV-Gutachten/Schätzung basiert und eine tatsächliche Rechnung
(Werkstatt, SV-Honorar, etc.) einen anderen Betrag hat:
  Schritt 1: alte Schätzposition deaktivieren → `deaktiviere_zahlungsposition` (wird nicht mehr mitgerechnet)
  Schritt 2: neue Position mit tatsächlichem Betrag anlegen → `erstelle_zahlungspositionen`
  Schritt 3: neue Position buchen → `buche_zahlung`
NIEMALS den SOLL-Betrag einer alten Position ändern wenn sie durch eine neue ersetzt wird —
deaktivieren ist sauberer und erhält die Übersicht.

RVG-POSITIONEN — DREI TOOLS, KLARE REGELN:
- `berechne_rvg` erstellt DREI getrennte Zahlungspositionen (1,3 Geschäftsgebühr + Auslagenpauschale + 19% USt).
- NIEMALS RVG-Positionen über `erstelle_zahlungspositionen` anlegen — ausschließlich `berechne_rvg` nutzen!
- Wenn User "erstelle Gebühren", "berechne RVG", "Finalabrechnung" oder ähnliches sagt: `berechne_rvg` aufrufen.
- Diese Positionen sind nach der Erstellung OFFEN — die Versicherung hat die RVG noch NICHT bezahlt.
- Das Finalschreiben FORDERT die RVG-Zahlung — es bestätigt sie NICHT als eingegangen.
- NIEMALS `buche_zahlung` direkt für RVG-Positionen aufrufen!
  Stattdessen: `buche_rvg_zahlung` — bucht alle drei Positionen auf einmal als bezahlt.
  Nutze `buche_rvg_zahlung` wenn User sagt: "RVG ist eingegangen", "Gebühren wurden bezahlt",
  "Versicherung hat die Anwaltskosten überwiesen" o.ä.

ANDERE AKTIONEN (Aufgabe erstellen, Status ändern):
- AUFGABE ERSTELLEN: Rufe `erstelle_aufgabe` SOFORT auf wenn der User eine Aufgabe erstellen möchte — kein Bestätigungsschritt notwendig. Falls der User kein Datum nennt, frage zuerst "Bis wann?" und warte auf die Antwort, bevor du das Tool aufrufst.
- STATUS ÄNDERN: Kündige an und warte auf Bestätigung ("Ja", "Ok", "Mach das" etc.), bevor du `aendere_aktenstatus` aufrufst.
- NIEMALS proaktiv vorschlagen den Akte-Status zu schließen — nur wenn der User explizit darum bittet.
- WICHTIG: Rufe Tools TATSÄCHLICH auf — antworte NIEMALS nur mit Text "Aufgabe erstellt" oder "Status geändert" ohne den entsprechenden Tool-Aufruf durchzuführen!
- Du darfst einen KURZEN Satz schreiben während du eine Aktion ausführst (z.B. "Aufgabe wird erstellt..." oder "Speichere den Brief...") — aber IMMER zusammen mit dem Tool-Call in DERSELBEN Antwort. Nie Text ohne Tool-Call wenn eine Aktion gemeint ist.

ZAHLUNGSMONITOR & BANKBEWEGUNGEN — WIE ES ZUSAMMENHÄNGT:
Der Zahlungsmonitor ist ein separates Modul wo CSV-Kontoauszüge (CommerzBank) importiert werden.
Jede Bankbewegung (Buchungszeile) kann manuell oder per KI einer Zahlungsposition zugeordnet werden.

Datenfluss: Bankbewegung (CSV-Import) → Zahlungsabgleich → Zahlungsposition
- Eine Bankbewegung ist OFFEN solange sie keiner Position zugeordnet ist
- Eine Bankbewegung wird ZUGEORDNET wenn sie mit einem Zahlungsabgleich verknüpft ist
- Der Zahlungsabgleich enthält Details: wer hat gezahlt, wann, wie viel, wohin weitergeleitet

Was `get_finanzdaten` jetzt liefert:
- Jede Position enthält ein `abgleich`-Objekt (null wenn kein Abgleich existiert)
- Im Abgleich steht: zahlungsstatus, eingegangen_betrag, eingegangen_datum, empfaenger
- Und: bankbewegung_id + bankbewegung_betrag falls eine Bankbewegung zugeordnet ist

Wann welches Tool:
- User fragt "ist ein Zahlungseingang da?" → `get_bankbewegungen` aufrufen
- Zahlung ist im Abgleich sichtbar (get_finanzdaten → abgleich.zahlungsstatus=EINGEGANGEN) → bereits erfasst
- User sagt "buche den Eingang" für eine Schadensposition → `aktualisiere_zahlungsabgleich` ODER `buche_zahlung`
- User sagt "RVG wurde bezahlt" → `buche_rvg_zahlung`

KOMBINIERTE AUFGABEN — PFLICHT-KETTE (nicht unterbrechen):
Wenn der User mehrere Dinge auf einmal verlangt (z.B. "buche alles und erstelle einen Brief"),
führe ALLE Schritte in einer einzigen Antwort durch — ohne zwischendurch Text zu schreiben:

Beispiel "Buche alle Zahlungen + RVG + Finalschreiben":
  Schritt A: get_finanzdaten aufrufen und Positionen prüfen
  Schritt B: Für jede SCHADEN-Position (Reparatur, Mietwagen, SV-Honorar, Kostenpauschale):
             SOLL mit Dokumenten vergleichen. Falls SOLL falsch → User fragen, korrigieren, buchen.
             Nur ERHALTENE Zahlungen von der Versicherung buchen.
             RVG-Positionen NIEMALS in diesem Schritt buchen (die sind noch OFFEN).
  Schritt C: berechne_rvg aufrufen → neue RVG-Position wird erstellt (bleibt OFFEN, nicht buchen!)
  Schritt D: Brief-Entwurf mit RVG-FORDERUNG in den Chat zeigen:
             "Wir fordern unsere Rechtsanwaltsgebühren in Höhe von [X€] bis [Datum]."
             NICHT: "RVG ist in diesem Betrag enthalten" — das ist falsch!
  → ERST nach dem Brief-Entwurf stoppen und auf User-Bestätigung warten (dann speichern).

NIEMALS nach Schritt A, B oder C stoppen und auf weitere Anweisungen warten —
die Kette MUSS bis zum Brief-Entwurf durchlaufen.

INTELLIGENTE BUCHUNGSPRÜFUNG (PFLICHT vor jedem buche_zahlung):
Du bist ein Assistent, kein blinder Tool-Executor. Bevor du eine Zahlung buchst:
- Vergleiche den SOLL-Betrag jeder Finanzposition mit den DOKUMENTEN in der Akte (RAG-Chunks oben).
- Wenn ein Dokument (z.B. "SV-Rechnung", "Gutachten", "Kostenvoranschlag", "Versicherungsschreiben")
  einen anderen Betrag für diese Position nennt als der SOLL-Betrag im Finanz-Tab:
  Weise den User KONKRET und AKTIV darauf hin — nenne das Dokument und beide Beträge.
  Beispiel: "Im Finanz-Tab steht SV-Honorar mit 500€, aber laut der 'SV-Rechnung' in der Akte
  beträgt der Betrag 999,34€. Laut dem Versicherungsschreiben wurde dieser Betrag direkt an den
  Sachverständigen überwiesen. Soll ich den SOLL-Betrag auf 999,34€ korrigieren und als bezahlt buchen?"
- Warte auf Bestätigung des Users bevor du buchst.
- `buche_zahlung` hat optionalen Parameter `soll_betrag` — nutze ihn wenn SOLL korrigiert werden muss.
- Nenne IMMER das konkrete Dokument das den abweichenden Betrag belegt.

FINALSCHREIBEN / RVG-ABSCHLUSSSCHREIBEN AN VERSICHERUNG:
Nach berechne_rvg gibt das System ein fertiges Feld `brief_text_vorlage` und `betreff_vorlage` zurück.
PFLICHT: Verwende diese Felder EXAKT 1:1 als `brief_text` und `betreff` in erstelle_brief.
KEINERLEI Umformulierungen, Ergänzungen oder Kürzungen — der Text ist rechtlich geprüft und fix.
Einzige Ausnahme: brief_text_vorlage ist leer oder fehlt → dann erst den User fragen.
"""

        tools = [
            {
                "function_declarations": [
                    {
                        "name": "get_finanzdaten",
                        "description": "Aktuelle Zahlungspositionen und Finanzdaten der Akte abrufen",
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {
                                "akte_id": {"type": "INTEGER", "description": "Die Akte-ID"}
                            },
                            "required": ["akte_id"]
                        }
                    },
                    {
                        "name": "erstelle_aufgabe",
                        "description": "Eine neue Aufgabe für die Akte erstellen",
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {
                                "akte_id": {"type": "INTEGER"},
                                "titel": {"type": "STRING", "description": "Titel der Aufgabe"},
                                "beschreibung": {"type": "STRING", "description": "Beschreibung (optional)"},
                                "prioritaet": {"type": "STRING", "enum": ["hoch", "mittel", "niedrig"]},
                                "faellig_am": {"type": "STRING", "description": "Fälligkeitsdatum ISO-Format YYYY-MM-DD — PFLICHT. Falls der User kein Datum nennt, frage erst danach bevor du das Tool aufrufst."}
                            },
                            "required": ["akte_id", "titel", "faellig_am"]
                        }
                    },
                    {
                        "name": "erstelle_frist",
                        "description": "Eine neue Frist (Deadline) für die Akte eintragen. Nutze dies IMMER, wenn der User explizit eine Frist, Deadline oder ähnliches setzen möchte.",
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {
                                "akte_id": {"type": "INTEGER"},
                                "bezeichnung": {"type": "STRING", "description": "Bezeichnung der Frist, z.B. 'Widerspruchsfrist', 'Frist zur Stellungnahme'"},
                                "frist_datum": {"type": "STRING", "description": "Datum der Frist im ISO-Format YYYY-MM-DD — PFLICHT. Falls der User kein Datum nennt, frage erst danach bevor du das Tool aufrufst."},
                                "prioritaet": {"type": "STRING", "enum": ["hoch", "mittel", "niedrig"]}
                            },
                            "required": ["akte_id", "bezeichnung", "frist_datum"]
                        }
                    },
                    {
                        "name": "aendere_aktenstatus",
                        "description": "Den Status der Akte ändern (z.B. auf Geschlossen setzen)",
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {
                                "akte_id": {"type": "INTEGER"},
                                "neuer_status": {"type": "STRING", "enum": ["Offen", "Geschlossen", "Archiviert"]}
                            },
                            "required": ["akte_id", "neuer_status"]
                        }
                    },
                    {
                        "name": "berechne_rvg",
                        "description": "RVG-Gebühren für eine Akte berechnen und drei Zahlungspositionen anlegen (1,3 Geschäftsgebühr + Auslagenpauschale + 19% USt). Erstellt außerdem das RVG-Abschlussschreiben automatisch — KEIN erstelle_brief danach nötig! IMMER aufrufen wenn: (1) User RVG-Gebühren erstellen/berechnen möchte, (2) User ein RVG-Schreiben anfordert, (3) Finalabrechnung. NIEMALS erstelle_zahlungspositionen für RVG nutzen — ausschließlich dieses Tool!",
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {
                                "akte_id": {"type": "INTEGER", "description": "Die Akte-ID"}
                            },
                            "required": ["akte_id"]
                        }
                    },
                    {
                        "name": "entwerfe_brief",
                        "description": "Erstellt einen Brief-Entwurf über einen separaten, fokussierten KI-Call (Stage 2). IMMER nutzen, wenn ein Brief benötigt wird — schreibe niemals Brief-Fließtext direkt in die Chat-Antwort. AUSNAHME: RVG-Finalschreiben nach berechne_rvg — dort brief_text_vorlage direkt an erstelle_brief geben. Ablauf: Du sammelst Fakten aus der Akte + bereinigte juristische Argumente (aus NotebookLM falls vorhanden), übergibst sie strukturiert. Das Tool liefert brief_text und betreff_vorschlag zurück — die zeigst du 1:1 im Chat mit der Rückfrage 'Soll ich diesen Brief so speichern?'",
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {
                                "akte_id": {"type": "INTEGER"},
                                "brief_zweck": {"type": "STRING", "description": "Kurze Kategorie des Briefes in Snake-Case. Beispiele: 'erstanschreiben_versicherung', 'erstanschreiben_mandant', 'widerspruch_sv_honorar_kuerzung', 'widerspruch_nutzungsausfall', 'mahnung_vor_klage', 'sachstandsinfo_mandant'. Wird für Goldstandard-RAG-Query verwendet — je präziser, desto bessere Stilvorlagen."},
                                "empfaenger": {"type": "STRING", "enum": ["versicherung", "mandant"], "description": "'versicherung' = an Gegner/Versicherung adressiert; 'mandant' = an Mandant adressiert"},
                                "ton": {"type": "STRING", "enum": ["forsch", "sachlich", "deeskalierend"], "description": "Tonvorgabe für Stage 2. Schlage anhand Kontext vor: Erstanschreiben = sachlich; zweiter Widerspruch / Mahnung = forsch; Schreiben an eigenen Mandanten = sachlich oder deeskalierend. User kann per Chat korrigieren — dann Tool erneut mit angepasstem ton rufen."},
                                "fakten": {
                                    "type": "ARRAY",
                                    "description": "Kuratierte Fakten aus der Akte, die in den Brief eingebaut werden sollen. NUR belegbare Fakten — keine Vermutungen. Stage 2 hat KEINEN Akten-Volltext und nutzt ausschließlich diese Liste.",
                                    "items": {
                                        "type": "OBJECT",
                                        "properties": {
                                            "typ": {"type": "STRING", "description": "Art des Faktums, z.B. 'unfall_datum', 'schadenposition', 'offener_betrag', 'mandant_name', 'gegner_name', 'kennzeichen', 'aktenzeichen_vers', 'fahrzeug', 'zahlungseingang'"},
                                            "wert": {"type": "STRING", "description": "Der konkrete Wert, z.B. '10.03.2026' oder 'SV-Honorar 999,34€'"},
                                            "beleg_dokument_titel": {"type": "STRING", "description": "Optional: Titel des Quell-Dokuments in der Akte für Zitiergebot, z.B. 'SV-Rechnung vom 12.03.2026'"}
                                        },
                                        "required": ["typ", "wert"]
                                    }
                                },
                                "juristische_argumente": {
                                    "type": "ARRAY",
                                    "description": "Bereinigte juristische Argumente — bei NotebookLM-Input: Kern-Thesen extrahieren, akademische Überschriften und Gutachter-Jargon weglassen. Leere Liste erlaubt bei reinen Erstanschreiben ohne Streitpunkt.",
                                    "items": {
                                        "type": "OBJECT",
                                        "properties": {
                                            "kern_these": {"type": "STRING", "description": "Eine-Satz-These, z.B. 'Versicherung darf nicht pauschal auf Schwacke-Tabelle zurückgreifen, wenn konkrete SV-Feststellung vorliegt'"},
                                            "begruendung": {"type": "STRING", "description": "2-3 Sätze Begründung in Klartext — kein Gutachter-Jargon, keine Überschriften, kein 'Prüfungsmaßstab:'"},
                                            "rechtsprechung": {"type": "STRING", "description": "Optional: Rechtsprechungs-Zitat in Kurzform, z.B. 'BGH VI ZR 320/15'"}
                                        },
                                        "required": ["kern_these", "begruendung"]
                                    }
                                },
                                "forderung": {
                                    "type": "OBJECT",
                                    "description": "Optional: Konkrete Forderung am Briefende.",
                                    "properties": {
                                        "betrag_eur": {"type": "NUMBER", "description": "Geforderter Betrag in Euro"},
                                        "frist_datum": {"type": "STRING", "description": "Zahlungsfrist ISO YYYY-MM-DD"},
                                        "beschreibung": {"type": "STRING", "description": "Freitext-Beschreibung wenn kein Betrag/Frist (z.B. 'Stellungnahme zum Vorfall')"}
                                    }
                                },
                                "besondere_hinweise": {"type": "STRING", "description": "Optional: Flexibilitäts-Ventil für Edge-Cases, z.B. 'Keine Klagandrohung — Mandant möchte zunächst deeskalierend bleiben' oder 'Bitte auf kürzlich ergangenes OLG-Urteil Bezug nehmen'."}
                            },
                            "required": ["akte_id", "brief_zweck", "empfaenger", "ton", "fakten", "juristische_argumente"]
                        }
                    },
                    {
                        "name": "erstelle_brief",
                        "description": "Speichert einen vom User bestätigten Brief als Dokument (.docx + DB). Rufe dies NUR nach ausdrücklicher User-Bestätigung eines zuvor durch entwerfe_brief (oder berechne_rvg.brief_text_vorlage) generierten Entwurfs. Der brief_text ist der Entwurf-Text 1:1 — keine Umformulierung. Briefkopf, Datum, Anrede und Signatur werden automatisch aus der Vorlage ergänzt.",
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {
                                "akte_id": {"type": "INTEGER"},
                                "empfaenger": {"type": "STRING", "enum": ["versicherung", "mandant"], "description": "'versicherung' = an Gegner/Versicherung adressiert; 'mandant' = an Mandant adressiert"},
                                "betreff": {"type": "STRING", "description": "Betreffzeile des Briefes. NUR das Thema, z.B. 'Schadensregulierung – Unfall vom 10.03.2026' oder 'Sachstandsinformation'. NIEMALS Aktenzeichen (z.B. '08.26.awr') einschließen — das wird vom Template automatisch ergänzt."},
                                "brief_text": {"type": "STRING", "description": "Nur der Fließtext des Briefinhalts. KEIN Briefkopf, KEIN Datum, KEINE Anrede ('Sehr geehrte...'), KEIN Schluss ('Mit freundlichen Grüßen'), KEIN 'Unser Zeichen', KEIN Aktenzeichen. Diese Teile werden automatisch aus der Vorlage ergänzt. FORMATIERUNG: Absätze und Listenpunkte mit doppelter Leerzeile (\\n\\n) trennen — einzelnes \\n wird zu Leerzeichen zusammengeführt."}
                            },
                            "required": ["akte_id", "empfaenger", "betreff", "brief_text"]
                        }
                    },
                    {
                        "name": "aktualisiere_ki_memory",
                        "description": "KI-Memory der Akte mit einem neuen Fakteneintrag aktualisieren. "
                                       "NUR nach erfolgreich ausgeführter Aktion aufrufen (nicht spekulativ). "
                                       "Beispiel: 'Erstanschreiben Vers. erstellt 24.03.2026'",
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {
                                "akte_id": {"type": "INTEGER"},
                                "eintrag": {"type": "STRING", "description": "Faktischer Eintrag, max. 1-2 Sätze"}
                            },
                            "required": ["akte_id", "eintrag"]
                        }
                    },
                    {
                        "name": "erstelle_zahlungspositionen",
                        "description": "Zahlungspositionen (Forderungen) in den Finanzen der Akte anlegen. Nutze dies für Schaden-Positionen: Gutachten, Kostenpauschale, Reparaturkosten, Sachverständigengebühren. NICHT für RVG-Gebühren — dafür gibt es `berechne_rvg`.",
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {
                                "akte_id": {"type": "INTEGER"},
                                "positionen": {
                                    "type": "ARRAY",
                                    "items": {
                                        "type": "OBJECT",
                                        "properties": {
                                            "beschreibung": {"type": "STRING", "description": "Bezeichnung der Position, z.B. 'Kostenpauschale', 'Schadensgutachten (netto)'"},
                                            "soll_betrag": {"type": "NUMBER", "description": "Betrag in Euro (Forderung)"},
                                            "category": {"type": "STRING", "description": "Kategorie: Gutachten | SV-Kosten | Reparatur | Mietfahrzeug | Schmerzensgeld | Kostenpauschale | Sonstiges (NIEMALS RVG — dafür berechne_rvg nutzen!)"}
                                        },
                                        "required": ["beschreibung", "soll_betrag", "category"]
                                    },
                                    "description": "Liste der anzulegenden Zahlungspositionen"
                                }
                            },
                            "required": ["akte_id", "positionen"]
                        }
                    },
                    {
                        "name": "buche_zahlung",
                        "description": (
                            "Zahlungseingang (Haben-Betrag) gegen eine bestehende Zahlungsposition buchen. "
                            "Nutze dies wenn die Versicherung gezahlt hat und der Betrag im Finanz-Tab eingetragen werden soll. "
                            "Die zahlungsposition_id findest du in den FINANZDATEN des Kontexts (Feld 'id'). "
                            "Status wird automatisch gesetzt: BEZAHLT wenn haben >= soll, sonst TEILBEZAHLT. "
                            "Falls der SOLL-Betrag der Position falsch ist, kann er gleichzeitig mit soll_betrag korrigiert werden."
                        ),
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {
                                "zahlungsposition_id": {"type": "INTEGER", "description": "ID der Zahlungsposition aus den FINANZDATEN (Feld 'id')"},
                                "haben_betrag": {"type": "NUMBER", "description": "Eingegangener Betrag in Euro"},
                                "soll_betrag": {"type": "NUMBER", "description": "Optional: korrigierter SOLL-Betrag falls der aktuelle SOLL-Wert falsch ist"},
                            },
                            "required": ["zahlungsposition_id", "haben_betrag"]
                        }
                    },
                    {
                        "name": "buche_rvg_zahlung",
                        "description": (
                            "RVG-Zahlungseingang buchen — wenn die Versicherung die Rechtsanwaltsgebühren überwiesen hat. "
                            "Bucht automatisch alle drei RVG-Positionen (Geschäftsgebühr + Auslagenpauschale + USt) als vollständig bezahlt. "
                            "IMMER dieses Tool nutzen wenn der User sagt 'RVG ist eingegangen', 'Gebühren wurden bezahlt', "
                            "'Versicherung hat die Anwaltskosten überwiesen' o.ä. — NIEMALS buche_zahlung 3× manuell aufrufen!"
                        ),
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {
                                "akte_id": {"type": "INTEGER", "description": "Die Akte-ID"},
                            },
                            "required": ["akte_id"]
                        }
                    },
                    {
                        "name": "deaktiviere_zahlungsposition",
                        "description": (
                            "Eine Zahlungsposition deaktivieren (wird aus Gegenstandswert und Saldo rausgerechnet). "
                            "Nutze dies wenn eine alte Schätzposition (z.B. 'Reparaturkosten netto' aus SV-Gutachten) "
                            "durch eine neue tatsächliche Rechnung ersetzt wird. "
                            "Ablauf: 1. alte Position deaktivieren → 2. neue Position anlegen (erstelle_zahlungspositionen) → 3. buchen."
                        ),
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {
                                "zahlungsposition_id": {"type": "INTEGER", "description": "ID der zu deaktivierenden Position aus den FINANZDATEN (Feld 'id')"},
                            },
                            "required": ["zahlungsposition_id"]
                        }
                    },
                    {
                        "name": "aktualisiere_zahlungsabgleich",
                        "description": (
                            "Zahlungsabgleich für eine Zahlungsposition erstellen oder aktualisieren. "
                            "Nutze dies wenn eine Zahlung eingegangen ist und der Zahlungsstatus samt Details "
                            "(Betrag, Datum, Empfänger, Weiterleitung) im Finanzsystem festgehalten werden soll. "
                            "Falls der eingegangene Betrag kleiner als der SOLL-Betrag ist (Kürzung), "
                            "rufe DANACH zusätzlich `erstelle_aufgabe` auf: "
                            "Titel 'Kürzung erkannt – bitte prüfen', Priorität 'hoch'."
                        ),
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {
                                "position_id": {"type": "INTEGER", "description": "ID der Zahlungsposition (aus FINANZDATEN)"},
                                "zahlungsstatus": {
                                    "type": "STRING",
                                    "enum": ["OFFEN", "EINGEGANGEN", "ANGEFOCHTEN", "GEKUERZT_AKZEPTIERT", "WEITERGELEITET", "DIREKT_BEZAHLT", "ERLEDIGT"],
                                    "description": "Zahlungsstatus: EINGEGANGEN wenn Betrag einging, WEITERGELEITET wenn an Mandant weitergeleitet, ANGEFOCHTEN bei Widerspruch, DIREKT_BEZAHLT wenn direkt an Dritten (Werkstatt/SV) gezahlt"
                                },
                                "eingegangen_betrag": {"type": "NUMBER", "description": "Tatsächlich eingegangener Betrag in Euro"},
                                "eingegangen_datum": {"type": "STRING", "description": "Datum des Zahlungseingangs YYYY-MM-DD"},
                                "empfaenger": {
                                    "type": "STRING",
                                    "enum": ["KANZLEI", "WERKSTATT", "SV", "MANDANT", "SONSTIGER"],
                                    "description": "Wer hat das Geld empfangen? KANZLEI = Zahlung kam auf Kanzleikonto"
                                },
                                "empfaenger_name": {"type": "STRING", "description": "Name des Empfängers (bei WERKSTATT/SV/SONSTIGER), z.B. 'Werkstatt Huber GmbH'"},
                                "weiterleitung_betrag": {"type": "NUMBER", "description": "Betrag der an Mandant weitergeleitet wurde (nur bei WEITERGELEITET)"},
                                "weiterleitung_datum": {"type": "STRING", "description": "Datum der Weiterleitung YYYY-MM-DD (nur bei WEITERGELEITET)"},
                                "notiz": {"type": "STRING", "description": "Interne Notiz, z.B. Referenznummer der Versicherung oder Abweichungsgrund"}
                            },
                            "required": ["position_id", "zahlungsstatus"]
                        }
                    },
                    {
                        "name": "get_bankbewegungen",
                        "description": (
                            "Offene Bankbewegungen (Kontoeingänge) für diese Akte abrufen — aus dem Zahlungsmonitor. "
                            "Zeigt CSV-importierte Buchungszeilen die noch keiner Position zugeordnet sind (status=OFFEN) "
                            "sowie bereits zugeordnete Bewegungen dieser Akte. "
                            "Nutze dies wenn der User fragt ob ein Zahlungseingang im System ist, "
                            "oder welche Bankbewegungen zu dieser Akte gehören."
                        ),
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {
                                "akte_id": {"type": "INTEGER", "description": "Die Akte-ID"},
                            },
                            "required": ["akte_id"]
                        }
                    },
                    {
                        "name": "get_statistiken",
                        "description": (
                            "Kanzleiweite Statistiken für einen Zeitraum abrufen: Akten angelegt/geschlossen, "
                            "RVG-Gebühren berechnet, Zahlungseingänge, Fristen. "
                            "Nutze dies bei Fragen wie 'Wie viele Akten wurden diesen Monat angelegt?', "
                            "'Wie viel RVG haben wir diesen Monat generiert?', 'Was hat Alex diese Woche gemacht?'"
                        ),
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {
                                "zeitraum": {
                                    "type": "STRING",
                                    "enum": ["dieser_monat", "letzter_monat", "dieses_jahr", "letzte_30_tage"],
                                    "description": "Zeitraum der Auswertung (default: dieser_monat)"
                                },
                                "referent": {
                                    "type": "STRING",
                                    "description": "Optional: Sachbearbeiter-Name (Teilstring, z.B. 'Alex') zum Filtern"
                                }
                            },
                            "required": []
                        }
                    }
                ]
            }
        ]

        contents = []
        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})

        # Vertex AI erfordert mindestens einen Content — bei leeren messages (Analyse-Start) Dummy einfügen
        if not contents:
            contents = [{"role": "user", "parts": [{"text": "Analysiere diese Akte und gib mir eine strukturierte Übersicht mit Handlungsempfehlungen."}]}]

        from google.genai import types as genai_types
        config = genai_types.GenerateContentConfig(
            tools=tools,
            system_instruction=system_prompt,
            thinking_config=genai_types.ThinkingConfig(include_thoughts=False),
            temperature=0.7,  # Kreativität für Briefformulierungen; Regeln durch System-Prompt durchgesetzt
        )

        # Gemini aufrufen mit Function Calling
        try:
            response = await gemini.client.aio.models.generate_content(
                model=gemini.model_name,
                contents=contents,
                config=config,
            )
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "ResourceExhausted" in err_str or "quota" in err_str.lower():
                return {
                    "reply": "⏳ Gemini API Tageslimit erreicht. Bitte in einigen Minuten erneut versuchen.",
                    "actions_taken": []
                }
            raise

        def _find_all_fcs(resp):
            """Sammelt ALLE Function-Calls aus dem Response (für parallele Tool-Nutzung)."""
            if not resp.candidates:
                return []
            fcs = []
            for part in (resp.candidates[0].content.parts or []):
                fc = getattr(part, 'function_call', None)
                if fc and getattr(fc, 'name', None):
                    fcs.append(fc)
            return fcs

        actions_taken = []
        while True:
            fcs = _find_all_fcs(response)

            if not fcs:
                break  # Kein Tool-Call → fertig (Text-Antwort folgt)

            # Alle FCs ausführen (Gemini kann mehrere parallel senden)
            # WICHTIG: Anzahl FunctionResponses MUSS == Anzahl FunctionCalls sein (Vertex 400 sonst)
            response_parts = []
            for fc in fcs:
                try:
                    fc_args_dict = {k: v for k, v in fc.args.items()}
                except Exception:
                    fc_args_dict = dict(fc.args)

                # Gemini vergisst manchmal akte_id — aus Kontext auffüllen
                if "akte_id" not in fc_args_dict or not fc_args_dict.get("akte_id"):
                    fc_args_dict["akte_id"] = akte_id

                tool_result = await self._execute_chat_tool(fc.name, fc_args_dict)
                actions_taken.append({"tool": fc.name, "result": tool_result})

                response_parts.append(genai_types.Part(function_response=genai_types.FunctionResponse(
                    name=fc.name,
                    response={"result": tool_result}
                )))

            contents.append(response.candidates[0].content)  # type: ignore[union-attr]
            contents.append(genai_types.Content(role="user", parts=response_parts))

            try:
                response = await gemini.client.aio.models.generate_content(
                    model=gemini.model_name, contents=contents, config=config,
                )
            except Exception as e:
                err_str = str(e)
                if "429" in err_str or "ResourceExhausted" in err_str or "quota" in err_str.lower():
                    return {"reply": "⏳ Gemini API Tageslimit erreicht. Bitte in einigen Minuten erneut versuchen.", "actions_taken": actions_taken}
                raise

        try:
            reply_text = response.text if response.candidates else "Keine Antwort von KI."
        except ValueError:
            reply_text = "Die Anfrage konnte nicht verarbeitet werden. Bitte formuliere sie anders oder nutze eine der verfügbaren Aktionen."
        return {"reply": _strip_markdown(reply_text), "actions_taken": actions_taken}


# Singleton
query_service = QueryService()
