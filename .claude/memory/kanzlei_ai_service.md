# Kanzlei AI Service – Projektdetails

**Repo:** `C:\Entwicklung\Kanzlei_AI_Service`
**Zweck:** KI-Backend-Dienst für Kanzlei V3 – Endpunkte für KI-Extraktion, RAG, Vorlagen-Empfehlungen, Dokumenten-Verarbeitung.

## Tech-Stack
| Komponente | Technologie                        |
|------------|------------------------------------|
| Framework  | FastAPI (Python)                   |
| RAG-DB     | ChromaDB (lokale Datei-Datenbank)  |
| LLM Dev    | Google Gemini 2.0 Flash (API-Key)  |
| LLM Prod   | Ollama/Loki (lokal, 10.10.10.5)    |
| Embeddings | text-embedding-004 (Google API)    |
| Server     | Uvicorn (Port 5000)                |

## Projektstruktur
```
Kanzlei_AI_Service/
├── app/
│   ├── main.py                    # FastAPI App, alle Endpunkte
│   ├── config.py                  # pydantic-settings, .env
│   ├── job_tracker.py             # Async Job-Tracking
│   └── services/
│       ├── rag_store.py           # ChromaDB RAG ⚠️ KRITISCH
│       ├── orchestrator.py        # Workflow-Orchestrierung
│       ├── ai_extractor.py        # KI-Extraktion (E-Mail/Dokumente)
│       ├── ai_file_extractor.py   # Datei-Extraktion
│       ├── loki_client.py         # Loki/Ollama Client (Hybrid 2-Model)
│       ├── gemini_client.py       # Gemini Client
│       ├── vorlagen_suggest_service.py
│       ├── backend_client.py      # HTTP-Client für Kanzlei V3
│       ├── django_client.py
│       ├── email_parser.py
│       └── email_processor.py
├── rag_storage/                   # ⚠️ ChromaDB Daten – NIEMALS LÖSCHEN!
├── uploads/                       # Temp. Uploads (.gitignore)
├── logs/                          # (.gitignore)
└── .env / .env.example
```

## ⚠️ RAG-Datenbank (KRITISCH)
- **Pfad:** `./rag_storage/` – Collection: `kanzlei_wissen`
- Enthält eingespeiste Referenzschreiben, Vorlagen, Fallwissen
- Nicht im Git → **manuell sichern!**
- Backup: `xcopy /E /I rag_storage rag_storage_backup`

## Server starten
```bash
cd C:\Entwicklung\Kanzlei_AI_Service
venv\Scripts\activate
uvicorn app.main:app --reload --port 5000
# Docs: http://localhost:5000/docs
```

## Umgebungsvariablen (.env)
```
LLM_PROVIDER=gemini          # oder: loki
GEMINI_API_KEY=<key>
GEMINI_MODEL=gemini-2.0-flash
LOKI_URL=http://10.10.10.5:11434
LOKI_VISION_MODEL=llama-vision-work
LOKI_MAPPING_MODEL=qwen-work
BACKEND_URL=http://localhost:8000
SERVICE_PORT=5000
```

## Wichtige API-Endpunkte
| Methode | Pfad                  | Beschreibung                    |
|---------|-----------------------|---------------------------------|
| POST    | `/extract`            | E-Mail/Dokument KI-Extraktion   |
| POST    | `/rag/feed`           | Dokument in RAG einspeisen      |
| GET     | `/rag/stats`          | RAG Statistiken                 |
| DELETE  | `/rag/delete/{id}`    | Dokument aus RAG löschen        |
| POST    | `/suggest/vorlagen`   | Vorlagen-Empfehlung via RAG     |
| GET     | `/health`             | Service-Status                  |
| GET     | `/loki/status`        | Loki-Server-Status              |

## KI-Architektur (Hybrid Two-Model)
- **Dev:** Gemini 2.0 Flash (Google API)
- **Prod:** Loki/Ollama auf 10.10.10.5 – `llama-vision-work` (Vision) + `qwen-work` (Mapping)
- Bei Loki-Ausfall: automatischer Fallback auf Gemini
