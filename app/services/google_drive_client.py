"""
Google Drive Client — Kanzlei AI Service

Lädt PDF-Dateien (oder andere generierte Dateien) in Google Drive hoch und gibt die URL zurück.
Teilt die hochgeladene Datei automatisch mit dem konfigurierten Delegate-User.

Konfiguration (.env):
    GOOGLE_SERVICE_ACCOUNT_JSON  Pfad zur Service-Account-JSON-Datei
    GOOGLE_DELEGATE_EMAIL        E-Mail des Users, der Zugriff auf die Docs erhaelt
    GOOGLE_DRIVE_FOLDER_ID       (Optional) Folder ID, in dem die Dateien abgelegt werden sollen.

Ohne diese Variablen laeuft der Client im Mock-Modus (gibt None zurueck).
"""
import logging
import os
import io
from typing import Optional

logger = logging.getLogger(__name__)

SCOPES = [
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/drive.file',
]

class GoogleDriveClient:
    """
    Laedt Dateien in Google Drive hoch.
    
    Mock-Modus (kein Account konfiguriert):
      upload_pdf() gibt None zurueck. App bleibt funktionsfaehig.
      
    Echter Modus (GOOGLE_SERVICE_ACCOUNT_JSON gesetzt):
      upload_pdf() laedt eine Datei hoch, teilt sie und gibt die URL zurueck.
    """

    def __init__(self):
        self.service_account_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
        self.delegate_email = os.getenv("GOOGLE_DELEGATE_EMAIL", "")
        self.folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "")
        self.enabled = bool(
            self.service_account_json
            and os.path.exists(self.service_account_json)
            and self.delegate_email
        )

        if self.enabled:
            logger.info(f"Google Drive Client: aktiv (delegate: {self.delegate_email})")
        else:
            logger.info("Google Drive Client: inaktiv (GOOGLE_SERVICE_ACCOUNT_JSON fehlt oder nicht gefunden)")

    def upload_pdf(self, dateiname: str, pdf_bytes: bytes) -> Optional[str]:
        """
        Laedt eine PDF in Google Drive hoch und gibt die Web View Link URL zurueck.
        
        Args:
            dateiname: Name der Datei in Drive (z.B. "Brief_Mueller.pdf")
            pdf_bytes: Der binaere Inhalt der PDF-Datei
            
        Returns:
            Google Drive URL zur Datei oder None bei Fehler/Inaktivitaet
        """
        if not self.enabled:
            logger.debug("Google Drive: Mock-Modus — keine Datei hochgeladen.")
            return None

        try:
            return self._upload_pdf_impl(dateiname, pdf_bytes)
        except Exception as e:
            logger.error(f"Google Drive: Fehler beim Hochladen: {e}")
            return None

    def _upload_pdf_impl(self, dateiname: str, pdf_bytes: bytes) -> Optional[str]:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseUpload

        # 1. Credentials aus Service-Account-JSON laden
        creds = service_account.Credentials.from_service_account_file(
            self.service_account_json,
            scopes=SCOPES,
        )

        # 2. Drive Service erstellen
        drive_service = build('drive', 'v3', credentials=creds, cache_discovery=False)

        # 3. Datei-Metadaten vorbereiten
        file_metadata = {
            'name': dateiname,
            'mimeType': 'application/pdf'
        }
        
        if self.folder_id:
            file_metadata['parents'] = [self.folder_id]

        # 4. Media Upload Objekt erstellen
        media = MediaIoBaseUpload(
            io.BytesIO(pdf_bytes),
            mimetype='application/pdf',
            resumable=True
        )

        # 5. Hochladen
        file = drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink'
        ).execute()
        
        file_id = file.get('id')
        web_view_link = file.get('webViewLink')
        logger.info(f"Google Drive: Datei hochgeladen (ID: {file_id})")

        # 6. Berechtigungen setzen (Teilen mit Delegate)
        drive_service.permissions().create(
            fileId=file_id,
            body={
                'type': 'user',
                'role': 'reader', # Lese-Rechte fuer PDFs sind hier meist ausreichend
                'emailAddress': self.delegate_email,
            },
            sendNotificationEmail=False,
        ).execute()
        logger.info(f"Google Drive: Datei geteilt mit {self.delegate_email}")

        return web_view_link

# Singleton
google_drive_client = GoogleDriveClient()
