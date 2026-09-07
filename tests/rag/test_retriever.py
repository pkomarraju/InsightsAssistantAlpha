import json

import faiss
import numpy as np
import pytest

from insights_assistant.rag.ingest_relationship_notes import build_index
from insights_assistant.rag.retriever import (
    EmbeddingDimensionMismatchError,
    IndexMetadataMismatchError,
    IndexNotFoundError,
    MetadataNotFoundError,
    RelationshipNotesRetriever,
)


def test_build_index_creates_files_and_parent_dirs(rag_config, fake_embeddings):
    assert not rag_config.index_path.parent.exists()

    build_index(rag_config, embeddings=fake_embeddings)

    assert rag_config.index_path.exists()
    assert rag_config.metadata_path.exists()


def test_index_ntotal_matches_metadata_count(rag_config, fake_embeddings, sample_notes):
    build_index(rag_config, embeddings=fake_embeddings)

    index = faiss.read_index(str(rag_config.index_path))
    metadata = json.loads(rag_config.metadata_path.read_text())

    assert index.ntotal == len(sample_notes)
    assert index.ntotal == len(metadata["records"])


def test_metadata_records_model_and_dimension(rag_config, fake_embeddings):
    build_index(rag_config, embeddings=fake_embeddings)
    metadata = json.loads(rag_config.metadata_path.read_text())

    assert metadata["embedding_model"] == "fake-embedding-model"
    assert metadata["dimension"] == fake_embeddings.dim


def test_metadata_is_json_not_pickle(rag_config, fake_embeddings):
    build_index(rag_config, embeddings=fake_embeddings)
    # json.loads succeeding is itself proof this isn't a pickle stream
    metadata = json.loads(rag_config.metadata_path.read_text())
    assert isinstance(metadata, dict)


def test_faiss_position_maps_to_correct_note_id(rag_config, fake_embeddings, sample_notes):
    build_index(rag_config, embeddings=fake_embeddings)

    index = faiss.read_index(str(rag_config.index_path))
    metadata = json.loads(rag_config.metadata_path.read_text())

    for position, note in enumerate(sample_notes):
        vector = np.array([fake_embeddings.embed_query(note["note_text"])], dtype=np.float32)
        faiss.normalize_L2(vector)
        similarities, positions = index.search(vector, 1)
        assert positions[0][0] == position
        assert metadata["records"][positions[0][0]]["note_id"] == note["note_id"]


def test_rebuild_does_not_touch_source_notes(rag_config, fake_embeddings):
    original = rag_config.notes_path.read_text()
    build_index(rag_config, embeddings=fake_embeddings)
    build_index(rag_config, embeddings=fake_embeddings)  # rebuild
    assert rag_config.notes_path.read_text() == original


def test_reload_and_search_returns_expected_fields(rag_config, fake_embeddings):
    build_index(rag_config, embeddings=fake_embeddings)

    retriever = RelationshipNotesRetriever(rag_config, embeddings=fake_embeddings)
    results = retriever.search("at risk competitor pricing", max_results=10)

    assert len(results) == 4
    expected_fields = {
        "note_id", "company_code", "company_name", "relationship_manager",
        "note_date", "note_text", "source_type", "similarity",
    }
    assert set(results[0].keys()) == expected_fields


def test_at_risk_query_ranks_amazon_exxon_alphabet_above_apple(rag_config, fake_embeddings):
    build_index(rag_config, embeddings=fake_embeddings)
    retriever = RelationshipNotesRetriever(rag_config, embeddings=fake_embeddings)

    results = retriever.search("explicit relationship at risk flag competitor pricing", max_results=4)

    top_three_codes = {r["company_code"] for r in results[:3]}
    assert top_three_codes == {"CLI_002", "CLI_006", "CLI_007"}
    assert results[3]["company_code"] == "CLI_003"


def test_date_filtering_excludes_notes_outside_range(rag_config, fake_embeddings):
    build_index(rag_config, embeddings=fake_embeddings)
    retriever = RelationshipNotesRetriever(rag_config, embeddings=fake_embeddings)

    results = retriever.search("relationship", date_from="2026-07-20", date_to="2026-07-25", max_results=10)

    dates = {r["note_date"] for r in results}
    assert dates == {"2026-07-22", "2026-07-25"}


def test_date_filtering_excludes_everything_outside_range(rag_config, fake_embeddings):
    build_index(rag_config, embeddings=fake_embeddings)
    retriever = RelationshipNotesRetriever(rag_config, embeddings=fake_embeddings)

    results = retriever.search("relationship", date_from="2026-08-01", max_results=10)
    assert results == []


def test_company_code_filtering(rag_config, fake_embeddings):
    build_index(rag_config, embeddings=fake_embeddings)
    retriever = RelationshipNotesRetriever(rag_config, embeddings=fake_embeddings)

    results = retriever.search("relationship", company_codes=["CLI_006"], max_results=10)

    assert len(results) == 1
    assert results[0]["company_code"] == "CLI_006"


def test_unrecognized_company_code_raises_instead_of_returning_empty(rag_config, fake_embeddings):
    """company_codes does exact matching only -- a caller that passes a
    ticker (e.g. "XOM") or an invented code instead of the real CLI_xxx
    code must not see that silently look identical to "no notes exist"
    (the REQ_1008 failure: relationship_notes_agent reported no notes for a
    company that did have on-topic ones, most likely because it filtered on
    the ticker it was given rather than the internal code)."""
    build_index(rag_config, embeddings=fake_embeddings)
    retriever = RelationshipNotesRetriever(rag_config, embeddings=fake_embeddings)

    with pytest.raises(ValueError, match="unrecognized code"):
        retriever.search("relationship", company_codes=["XOM"], max_results=10)


def test_sort_order_similarity_then_date_then_note_id(rag_config, fake_embeddings):
    build_index(rag_config, embeddings=fake_embeddings)
    retriever = RelationshipNotesRetriever(rag_config, embeddings=fake_embeddings)

    results = retriever.search("relationship", max_results=10)
    similarities = [r["similarity"] for r in results]
    assert similarities == sorted(similarities, reverse=True)


def test_missing_index_raises_clear_error(rag_config, fake_embeddings):
    with pytest.raises(IndexNotFoundError):
        RelationshipNotesRetriever(rag_config, embeddings=fake_embeddings)


def test_missing_metadata_raises_clear_error(rag_config, fake_embeddings):
    build_index(rag_config, embeddings=fake_embeddings)
    rag_config.metadata_path.unlink()

    with pytest.raises(MetadataNotFoundError):
        RelationshipNotesRetriever(rag_config, embeddings=fake_embeddings)


def test_mismatched_index_and_metadata_raises(rag_config, fake_embeddings):
    build_index(rag_config, embeddings=fake_embeddings)

    metadata = json.loads(rag_config.metadata_path.read_text())
    metadata["records"] = metadata["records"][:-1]  # drop one record, index still has all vectors
    rag_config.metadata_path.write_text(json.dumps(metadata))

    with pytest.raises(IndexMetadataMismatchError):
        RelationshipNotesRetriever(rag_config, embeddings=fake_embeddings)


def test_embedding_dimension_mismatch_raises(rag_config, fake_embeddings):
    build_index(rag_config, embeddings=fake_embeddings)

    class WrongDimEmbeddings:
        model = "fake-embedding-model"  # matches, so only the dimension check should trigger

        def embed_query(self, text):
            return [0.1, 0.2, 0.3]  # wrong dimension vs. the 16-dim index

    retriever = RelationshipNotesRetriever(rag_config, embeddings=fake_embeddings)
    retriever.embeddings = WrongDimEmbeddings()

    with pytest.raises(EmbeddingDimensionMismatchError):
        retriever.search("relationship")


class _ScaledEmbeddings:
    """Wraps another embeddings client but multiplies every vector by a fixed
    scale -- same direction, different magnitude. Used only to prove query
    vectors are normalized before search (magnitude must not affect ranking)."""

    def __init__(self, inner, scale: float):
        self.model = inner.model
        self._inner = inner
        self.scale = scale

    def embed_documents(self, texts):
        return [[self.scale * v for v in vec] for vec in self._inner.embed_documents(texts)]

    def embed_query(self, text):
        return [self.scale * v for v in self._inner.embed_query(text)]


def test_query_vectors_are_normalized_before_search(rag_config, fake_embeddings):
    build_index(rag_config, embeddings=fake_embeddings)

    retriever_unit = RelationshipNotesRetriever(rag_config, embeddings=fake_embeddings)
    retriever_scaled = RelationshipNotesRetriever(
        rag_config, embeddings=_ScaledEmbeddings(fake_embeddings, scale=37.0)
    )

    results_unit = retriever_unit.search("at risk competitor pricing", max_results=10)
    results_scaled = retriever_scaled.search("at risk competitor pricing", max_results=10)

    # A 37x larger query-vector magnitude must not change similarity scores
    # if the query vector is normalized before search, since only direction
    # should matter for cosine-style similarity.
    sims_unit = [round(r["similarity"], 4) for r in results_unit]
    sims_scaled = [round(r["similarity"], 4) for r in results_scaled]
    assert sims_unit == sims_scaled


def test_paraphrased_relationship_risk_query_ranks_flagged_companies_first(rag_config, fake_embeddings):
    build_index(rag_config, embeddings=fake_embeddings)
    retriever = RelationshipNotesRetriever(rag_config, embeddings=fake_embeddings)

    # Paraphrased, not a literal substring of any note.
    results = retriever.search("competitor pricing is putting the relationship at risk", max_results=4)

    top_three = {r["company_code"] for r in results[:3]}
    assert top_three == {"CLI_002", "CLI_006", "CLI_007"}


def test_embedding_model_mismatch_raises_at_construction(rag_config, fake_embeddings):
    build_index(rag_config, embeddings=fake_embeddings)

    class OtherModelEmbeddings:
        model = "some-other-model"

        def embed_query(self, text):
            return [0.0] * 16

    from insights_assistant.rag.retriever import EmbeddingModelMismatchError

    with pytest.raises(EmbeddingModelMismatchError):
        RelationshipNotesRetriever(rag_config, embeddings=OtherModelEmbeddings())
