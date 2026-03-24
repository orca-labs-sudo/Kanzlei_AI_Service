# CLAUDE.md – Kanzlei AI Service

> Diese Datei gibt Claude Code den vollständigen Projektkontext.
> Sie wird automatisch beim Start von Claude Code eingelesen.

---

## Projektübersicht

**Kanzlei AI Service** ist der KI-Backend-Dienst für das Kanzlei V3 System.
Er stellt Endpunkte für KI-Extraktion, RAG (Retrieval-Augmented Generation),
Vorlagen-Empfehlungen und Dokumenten-Verarbeitung bereit.

- **Repo:** `c:\Entwiklung\Kanzlei_AI_Service`
- **Hauptprojekt:** `c:\Entwiklung\Kanzlei_V3` (ruft diesen Service auf)
- **Sprache der Dokumentation:** Deutsch

---

## Tech-Stack

| Komponente   | Technologie                                             |
|--------------|---------------------------------------------------------|
| Framework    | FastAPI (Python)                                        |
| RAG-DB       | ChromaDB (lokale Datei-Datenbank)                       |
| LLM Lokal    | Google Gemini 2.5 Flash (API-Key, `LLM_PROVIDER=gemini`)|
| LLM Prod     | Vertex AI — Gemini 2.5 Flash, europe-west4 (`LLM_PROVIDER=vertex`) |
| LLM Fallback | Ollama/Loki (lokal, 10.10.10.5, `LLM_PROVIDER=loki`)   |
| Embeddings   | text-embedding-004 (Google API)                         |
| Server       | Uvicorn (Port 5000)                                     |

---

## Projektstruktur

```
Kanzlei_AI_Service/
├── app/
│   ├── main.py                    # FastAPI App, alle Endpunkte
│   ├── config.py                  # Einstellungen (pydantic-settings, .env)
│   ├── job_tracker.py             # Async Job-Tracking
│   └── services/
│       ├── rag_store.py           # ChromaDB RAG-Implementierung ⚠️ KRITISCH
│       ├── orchestrator.py        # Workflow-Orchestrierung
│       ├── ai_extractor.py        # KI-Extraktion (E-Mail/Dokumente)
│       ├── ai_file_extractor.py   # Datei-Extraktion
│       ├── loki_client.py         # Loki/Ollama Client (Hybrid 2-Model)
│       ├── gemini_client.py       # Gemini Client
│       ├── vorlagen_suggest_service.py  # Vorlagen-Empfehlung via RAG
│       ├── backend_client.py      # HTTP-Client für Kanzlei V3 Backend
│       ├── django_client.py       # Django-API Client
│       ├── email_parser.py        # E-Mail Parsing
│       └── email_processor.py     # E-Mail Verarbeitung
├── uploads/                       # Temp. Uploads (in .gitignore)
├── logs/                          # Log-Dateien (in .gitignore)
├── rag_storage/                   # ⚠️ ChromaDB Daten – NIEMALS LÖSCHEN!
├── .env                           # Secrets (in .gitignore)
├── .env.example                   # Vorlage für .env
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

---

## ⚠️ RAG-Datenbank – KRITISCH

Die RAG-Datenbank ist der **Kern des KI-Gedächtnisses**.

- **Speicherort:** `./rag_storage/` (ChromaDB, lokale Dateien)
- **Collection:** `kanzlei_wissen`
- **Inhalt:** Eingespeiste Referenzschreiben, Vorlagen, Fallwissen
- **Sicherung:** Dieses Verzeichnis ist in `.gitignore` → **manuell sichern!**

### RAG-Daten sichern (vor Migration):
```bash
# Im Kanzlei_AI_Service-Verzeichnis:
xcopy /E /I rag_storage rag_storage_backup
# oder als ZIP:
Compress-Archive -Path rag_storage -DestinationPath rag_storage_backup_2026.zip
```

### RAG-Daten wiederherstellen:
```bash
# ZIP entpacken nach rag_storage/:
Expand-Archive -Path rag_storage_backup_2026.zip -DestinationPath .
```

---

## Ports & Kommunikation

| Service         | Port  | Beschreibung                    |
|-----------------|-------|---------------------------------|
| AI Service selbst| 5000 | FastAPI Uvicorn                 |
| Kanzlei Backend | 8001  | Django (wird von hier aufgerufen)|
| Loki/Ollama     | 11434 | Lokaler LLM-Server (10.10.10.5) |

---

## Umgebungsvariablen (`.env`)

```env
# LLM Provider: "gemini" = lokal (API-Key), "vertex" = Prod (DSGVO), "loki" = Ollama
LLM_PROVIDER=gemini

# Gemini Developer API (lokal / Fallback)
GEMINI_API_KEY=<dein_key>
GEMINI_MODEL=gemini-2.5-flash

# Vertex AI (Produktion — DSGVO-konform, EU-Region)
# LLM_PROVIDER=vertex
# VERTEX_PROJECT_ID=your-gcp-project-id
# VERTEX_LOCATION=europe-west4
# VERTEX_MODEL=gemini-2.5-flash
# GOOGLE_APPLICATION_CREDENTIALS=/app/google_service_account.json

# Loki / Ollama
LOKI_URL=http://10.10.10.5:11434
LOKI_VISION_MODEL=llama-vision-work
LOKI_MAPPING_MODEL=qwen-work

# Backend
BACKEND_URL=http://localhost:8000
BACKEND_API_TOKEN=<backend_token>

SERVICE_PORT=5000
DEBUG=true
```

---

## Server starten

```bash
# Im Projektverzeichnis (Windows):
venv\Scripts\activate
uvicorn app.main:app --reload --port 5000

# API-Docs aufrufen:
# http://localhost:5000/docs
```

---

## Wichtige API-Endpunkte

| Methode | Pfad                  | Beschreibung                    |
|---------|-----------------------|---------------------------------|
| POST    | `/extract`            | E-Mail/Dokument KI-Extraktion   |
| POST    | `/rag/feed`           | Dokument in RAG einspeisen      |
| GET     | `/rag/stats`          | RAG Statistiken (Füllstand)     |
| DELETE  | `/rag/delete/{id}`    | Dokument aus RAG löschen        |
| POST    | `/suggest/vorlagen`   | Vorlagen-Empfehlung via RAG     |
| GET     | `/health`             | Service-Status                  |
| GET     | `/loki/status`        | Loki-Server-Status              |

---

## KI-Architektur

### LLM Provider (via `LLM_PROVIDER` in `.env`)

| Provider | Umgebung | Auth | Modell |
|---|---|---|---|
| `gemini` | Lokal / Entwicklung | API-Key | gemini-2.5-flash |
| `vertex` | **Produktion** (DSGVO!) | Service Account | gemini-2.5-flash, europe-west4 |
| `loki` | Fallback (GPU-Server) | — | llama-vision-work + qwen-work |

**Logging-Label** in den Service-Logs:
- `[LLM: VERTEX AI]` — Vertex AI aktiv
- `[LLM: GEMINI API]` — Gemini Developer API aktiv

**Fallback-Logik (ai_extractor.py):** Loki → bei Fehler permanenter Wechsel auf Gemini/Vertex.

### Vertex AI Deployment (Voraussetzungen)
1. Vertex AI API im GCP-Projekt aktivieren
2. Service Account → Rolle **"Vertex AI User"** (`roles/aiplatform.user`)
3. `google_service_account.json` auf Server vorhanden (wird gemountet)
4. `.env.production`: `LLM_PROVIDER=vertex` + `VERTEX_PROJECT_ID=<id>`

### Rollback
Branch `gemini-ohne-vertex` = Stand vor Vertex-Migration (Gemini Developer API)

---

## Wichtige Konventionen

- **Sprache:** Alle Kommentare auf **Deutsch**
- **Kein Commit ohne Erlaubnis** des Users
- **RAG-Daten niemals löschen** ohne explizite Bestätigung
- **Keine Annahmen** – bei Unklarheiten fragen
- Der Service läuft **getrennt** von Docker Compose (Kanzlei_V3)
