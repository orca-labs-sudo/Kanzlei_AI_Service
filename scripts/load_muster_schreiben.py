import asyncio
import os
import glob
from pathlib import Path

# Adjust path so we can import app modules when running from project root
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.rag_store import rag_store

async def load_docs():
    """
    Liest alle .txt-Dateien aus rag_data/muster_schreiben/ 
    und speichert sie als Chunks im ChromaDB 'kanzlei_wissen' Store.
    """
    base_dir = Path(__file__).parent.parent / "rag_data" / "muster_schreiben"
    
    if not base_dir.exists() or not base_dir.is_dir():
        print(f"Fehler: Verzeichnis {base_dir} nicht gefunden.")
        return

    txt_files = list(base_dir.glob("*.txt"))
    if not txt_files:
        print(f"Keine .txt Dateien in {base_dir} gefunden.")
        return

    print(f"Gefunden: {len(txt_files)} Vorlagen in {base_dir}")

    total_chunks_loaded = 0

    for file_path in txt_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            if not content.strip():
                print(f"Überspringe leere Datei: {file_path.name}")
                continue
            
            # Use the chunker strategy as defined in the main import text endpoint
            from app.main import _chunk_text
            chunks = _chunk_text(content, chunk_size=500)
            
            if not chunks:
                 print(f"Überspringe {file_path.name}: Keine Chunks extrahiert.")
                 continue

            # Fall type extracted from the filename
            fall_typ = file_path.stem.replace("_", " ").title()
            
            ids = [f"muster_{file_path.stem}_{i}" for i in range(len(chunks))]
            metadatas = [{"source": file_path.name, "fall_typ": fall_typ, "document_id": f"muster_{file_path.stem}"} for _ in chunks]

            print(f"Lade {file_path.name} in die DB ({len(chunks)} Chunks) ...")

            success = await rag_store.add_documents(
                documents=chunks,
                metadatas=metadatas,
                ids=ids,
                collection_name="kanzlei_wissen"
            )

            if success:
                total_chunks_loaded += len(chunks)
                print(f"✓ {file_path.name} erfolgreich geladen.")
            else:
                print(f"✗ Fehler beim Speichern von {file_path.name} in ChromaDB.")

        except Exception as e:
            print(f"Fehler beim Verarbeiten von {file_path.name}: {e}")

    print(f"\nFertig! Insgesamt {total_chunks_loaded} Chunks in die RAG-Datenbank geladen.")
    
    stats = rag_store.get_stats()
    print("\nAktuelle DB Statistiken:")
    print(f"- Gesamtzahl Chunks (kanzlei): {stats.get('chunk_count', 0)}")
    print(f"- Gesamtzahl Dokumente (kanzlei): {stats.get('document_count', 0)}")
    
    # system_wissen Stats
    sys_stats_count = rag_store._system_collection.count() if rag_store._system_collection else 0
    print(f"- Gesamtzahl Chunks (system): {sys_stats_count}")

if __name__ == "__main__":
    asyncio.run(load_docs())
