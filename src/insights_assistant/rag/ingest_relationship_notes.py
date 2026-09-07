"""Build the FAISS index for relationship-manager notes.

Run: python -m insights_assistant.rag.ingest_relationship_notes

Reads the existing notes corpus (never modified by this script), embeds every
note's note_text with one consistent embedding model, and writes a FAISS
IndexFlatIP index plus a JSON metadata sidecar. Safe to re-run: it only ever
(re)writes the generated index/metadata files, never the source notes.
"""

import json

import faiss
import numpy as np
from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings

from insights_assistant.rag.config import RagConfig
from insights_assistant.rag.loader import load_notes

load_dotenv()


def _embed_notes(notes: list[dict], embeddings) -> np.ndarray:
    texts = [note["note_text"] for note in notes]
    vectors = embeddings.embed_documents(texts)
    matrix = np.ascontiguousarray(np.array(vectors, dtype=np.float32))
    faiss.normalize_L2(matrix)
    return matrix


def build_index(config: RagConfig | None = None, embeddings=None) -> dict:
    """Build and persist the FAISS index + metadata. Returns the metadata dict.

    `embeddings` is injectable (must expose `.embed_documents(list[str]) ->
    list[list[float]]`) so tests can supply a fake client with no network access.
    """
    config = config or RagConfig()
    notes = load_notes(config.notes_path)

    if embeddings is None:
        embeddings = OpenAIEmbeddings(model=config.embedding_model)

    matrix = _embed_notes(notes, embeddings)
    dimension = int(matrix.shape[1])

    index = faiss.IndexFlatIP(dimension)
    index.add(matrix)

    if index.ntotal != len(notes):
        raise RuntimeError(
            f"FAISS index has {index.ntotal} vectors but {len(notes)} notes were embedded"
        )

    config.index_path.parent.mkdir(parents=True, exist_ok=True)
    config.metadata_path.parent.mkdir(parents=True, exist_ok=True)

    faiss.write_index(index, str(config.index_path))

    metadata = {
        "embedding_model": config.embedding_model,
        "dimension": dimension,
        "count": len(notes),
        "records": notes,
    }
    config.metadata_path.write_text(json.dumps(metadata, indent=2))

    return metadata


def main() -> None:
    config = RagConfig()
    metadata = build_index(config)
    print(f"Indexed {metadata['count']} notes from {config.notes_path}")
    print(f"  embedding model: {metadata['embedding_model']}")
    print(f"  dimension:       {metadata['dimension']}")
    print(f"  index written:   {config.index_path}")
    print(f"  metadata written:{config.metadata_path}")


if __name__ == "__main__":
    main()
