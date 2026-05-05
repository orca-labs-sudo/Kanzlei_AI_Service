"""
Laedt System-Dokumentation in die ChromaDB Collection "system_wissen".

Ausfuehren:
  docker exec kanzlei-ai-service python scripts/load_system_doku.py

Lokal (wenn ChromaDB laeuft):
  cd Kanzlei_AI_Service
  python scripts/load_system_doku.py
"""
import os
import sys
import uuid

# Pfad zum app-Modul ergaenzen
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.rag_store import rag_store
import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

DOKU_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "rag_data", "system_doku")

CHUNK_SIZE = 500    # Zeichen pro Chunk
CHUNK_OVERLAP = 50  # Ueberlappung zwischen Chunks


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Zerlegt Text in ueberlappende Chunks."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - overlap
        if start >= len(text):
            break
    return chunks


async def load_all():
    if not os.path.exists(DOKU_DIR):
        logger.error(f"Verzeichnis nicht gefunden: {DOKU_DIR}")
        sys.exit(1)

    md_files = [f for f in os.listdir(DOKU_DIR) if f.endswith(".md")]
    if not md_files:
        logger.error("Keine .md Dateien gefunden.")
        sys.exit(1)

    total_chunks = 0

    for filename in sorted(md_files):
        thema = filename.replace(".md", "")
        filepath = os.path.join(DOKU_DIR, filename)

        with open(filepath, encoding="utf-8") as f:
            text = f.read()

        chunks = chunk_text(text)
        if not chunks:
            logger.warning(f"  {filename}: Leer, uebersprungen.")
            continue

        batch_size = 50
        file_ok = True
        for i in range(0, len(chunks), batch_size):
            chunk_batch = chunks[i : i + batch_size]
            id_batch = [f"sysdoku_{thema}_{j}_{uuid.uuid4().hex[:8]}" for j in range(i, i + len(chunk_batch))]
            meta_batch = [
                {"typ": "system_doku", "thema": thema, "source": filename}
                for _ in chunk_batch
            ]
            ok = await rag_store.add_documents(
                documents=chunk_batch,
                metadatas=meta_batch,
                ids=id_batch,
                collection_name="system_wissen"
            )
            if not ok:
                logger.error(f"  {filename}: Fehler beim Laden von Batch {i // batch_size + 1}.")
                file_ok = False
                break

        if file_ok:
            logger.info(f"  {filename}: {len(chunks)} Chunks geladen.")
            total_chunks += len(chunks)
        else:
            logger.error(f"  {filename}: Fehler beim Laden.")

    logger.info(f"\nFertig. {len(md_files)} Dateien, {total_chunks} Chunks in 'system_wissen' gespeichert.")


if __name__ == "__main__":
    asyncio.run(load_all())
