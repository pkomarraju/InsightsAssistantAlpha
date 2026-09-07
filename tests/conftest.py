import json

import pytest

from insights_assistant.rag.config import DEFAULT_NOTES_PATH, RagConfig

VOCAB = [
    "at", "risk", "competitor", "pricing", "relationship", "revenue",
    "decline", "service", "expansion", "churn", "critical", "stable",
]


class FakeEmbeddings:
    """Deterministic, network-free stand-in for OpenAIEmbeddings.

    Produces a bag-of-keywords vector so texts sharing more vocabulary with a
    query score more similar -- enough signal to exercise ranking and
    filtering without any real embedding model.
    """

    def __init__(self, model="fake-embedding-model", dim=16):
        self.model = model
        self.dim = dim

    def _vec(self, text: str) -> list[float]:
        words = text.lower()
        vec = [float(words.count(tok)) for tok in VOCAB]
        while len(vec) < self.dim:
            vec.append(0.0)
        return vec[: self.dim]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


@pytest.fixture
def fake_embeddings():
    return FakeEmbeddings()


@pytest.fixture
def sample_notes():
    return [
        {
            "note_id": "RMN_001",
            "company_code": "CLI_002",
            "company_name": "Amazon",
            "relationship_manager": "Marcus Ibe",
            "note_date": "2026-07-18",
            "source_type": "relationship_manager_note",
            "synthetic": True,
            "note_text": "The Amazon relationship is formally flagged as at risk due to competitor "
            "pricing pressure and revenue decline.",
        },
        {
            "note_id": "RMN_002",
            "company_code": "CLI_006",
            "company_name": "Exxon Mobil",
            "relationship_manager": "Theo Baptiste",
            "note_date": "2026-07-22",
            "source_type": "relationship_manager_note",
            "synthetic": True,
            "note_text": "Exxon Mobil relationship is currently at risk following service issues and "
            "a competitor pricing proposal.",
        },
        {
            "note_id": "RMN_003",
            "company_code": "CLI_007",
            "company_name": "Alphabet",
            "relationship_manager": "Naomi Kessler",
            "note_date": "2026-07-25",
            "source_type": "relationship_manager_note",
            "synthetic": True,
            "note_text": "Alphabet relationship explicitly flagged at risk after revenue decline and "
            "increased competitor activity.",
        },
        {
            "note_id": "RMN_004",
            "company_code": "CLI_003",
            "company_name": "Apple",
            "relationship_manager": "Priya Raman",
            "note_date": "2026-07-10",
            "source_type": "relationship_manager_note",
            "synthetic": True,
            "note_text": "Routine quarterly check-in with Apple treasury team, no concerns raised, "
            "relationship remains stable and healthy.",
        },
    ]


@pytest.fixture
def notes_file(tmp_path, sample_notes):
    path = tmp_path / "notes.json"
    path.write_text(json.dumps(sample_notes, indent=2))
    return path


@pytest.fixture
def rag_config(tmp_path, notes_file):
    return RagConfig(
        notes_path=notes_file,
        index_path=tmp_path / "indexes" / "notes.faiss",
        metadata_path=tmp_path / "indexes" / "notes.metadata.json",
        embedding_model="fake-embedding-model",
    )


@pytest.fixture
def real_corpus_rag_config(tmp_path):
    """Points at the real, existing 50-note corpus but writes generated
    index/metadata to a temp dir, so tests never touch the real generated
    files under src/insights_assistant/data/indexes/."""
    return RagConfig(
        notes_path=DEFAULT_NOTES_PATH,
        index_path=tmp_path / "indexes" / "notes.faiss",
        metadata_path=tmp_path / "indexes" / "notes.metadata.json",
        embedding_model="fake-embedding-model",
    )
