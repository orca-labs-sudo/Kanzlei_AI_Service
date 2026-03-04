"""
Google Docs Client — Kanzlei AI Service

Erstellt Google Docs aus KI-generierten Briefen und gibt die Doc-URL zurueck.
Teilt jedes erstellte Dokument automatisch mit dem konfigurierten Delegate-User.

Konfiguration (.env):
    GOOGLE_SERVICE_ACCOUNT_JSON  Pfad zur Service-Account-JSON-Datei
    GOOGLE_DELEGATE_EMAIL        E-Mail des Users, der Zugriff auf die Docs erhaelt

Ohne diese Variablen laeuft der Client im Mock-Modus (gibt None zurueck).
"""
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

SCOPES = [
    'https://www.googleapis.com/auth/documents',
    'https://www.googleapis.com/auth/drive.file',
]


class GoogleDocsClient:
    """
    Erstellt Google Docs aus Briefentwuerfen.

    Mock-Modus (kein Account konfiguriert):
      create_doc() gibt None zurueck. App bleibt voll funktionsfaehig.

    Echter Modus (GOOGLE_SERVICE_ACCOUNT_JSON gesetzt):
      create_doc() erstellt ein echtes Google Doc und gibt die URL zurueck.
    """

    def __init__(self):
        self.service_account_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
        self.delegate_email = os.getenv("GOOGLE_DELEGATE_EMAIL", "")
        self.enabled = bool(
            self.service_account_json
            and os.path.exists(self.service_account_json)
            and self.delegate_email
        )

        if self.enabled:
            logger.info(f"Google Docs Client: aktiv (delegate: {self.delegate_email})")
        else:
            logger.info("Google Docs Client: inaktiv (GOOGLE_SERVICE_ACCOUNT_JSON fehlt oder nicht gefunden)")

    def create_doc(self, titel: str, inhalt: str) -> Optional[str]:
        """
        Erstellt ein Google Doc mit dem gegebenen Titel und Inhalt.

        Args:
            titel:  Titel des Dokuments (wird als Doc-Name verwendet)
            inhalt: Vollstaendiger Brieftext (Fliesstext ohne HTML)

        Returns:
            URL des erstellten Docs, oder None wenn deaktiviert/Fehler.
        """
        if not self.enabled:
            logger.debug("Google Docs: Mock-Modus — kein Doc erstellt.")
            return None

        try:
            return self._create_doc_impl(titel, inhalt)
        except Exception as e:
            logger.error(f"Google Docs: Fehler beim Erstellen des Docs: {e}")
            return None

    def _create_doc_impl(self, titel: str, inhalt: str) -> Optional[str]:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        # 1. Credentials aus Service-Account-JSON laden
        creds = service_account.Credentials.from_service_account_file(
            self.service_account_json,
            scopes=SCOPES,
        )

        # 2. Leeres Google Doc anlegen
        docs_service = build('docs', 'v1', credentials=creds, cache_discovery=False)
        doc = docs_service.documents().create(body={'title': titel}).execute()
        doc_id = doc['documentId']
        logger.info(f"Google Docs: Doc erstellt (ID: {doc_id})")

        # 3. Text via batchUpdate einfuegen
        docs_service.documents().batchUpdate(
            documentId=doc_id,
            body={
                'requests': [{
                    'insertText': {
                        'location': {'index': 1},
                        'text': inhalt,
                    }
                }]
            }
        ).execute()

        # 4. Drive API: Doc mit Delegate-User teilen (Editor-Rechte)
        drive_service = build('drive', 'v3', credentials=creds, cache_discovery=False)
        drive_service.permissions().create(
            fileId=doc_id,
            body={
                'type': 'user',
                'role': 'writer',
                'emailAddress': self.delegate_email,
            },
            sendNotificationEmail=False,
        ).execute()
        logger.info(f"Google Docs: Doc geteilt mit {self.delegate_email}")

        return self._build_doc_url(doc_id)

    def _build_doc_url(self, doc_id: str) -> str:
        """Erstellt die Doc-URL mit authuser-Parameter fuer korrekten Account."""
        base = f"https://docs.google.com/document/d/{doc_id}/edit"
        if self.delegate_email:
            return f"{base}?authuser={self.delegate_email}"
        return base


# Singleton
google_docs_client = GoogleDocsClient()
