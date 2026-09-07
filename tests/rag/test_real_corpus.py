"""Tests against the real, final 50-note corpus at
src/insights_assistant/data/relationship_manager_notes.json.

These never write to src/insights_assistant/data/indexes/ -- ingestion runs
against a temp directory via the real_corpus_rag_config fixture, and the
source notes file is never opened for writing.
"""

from insights_assistant.rag.config import DEFAULT_NOTES_PATH
from insights_assistant.rag.ingest_relationship_notes import build_index
from insights_assistant.rag.loader import load_notes
from insights_assistant.rag.retriever import RelationshipNotesRetriever

EXPECTED_AT_RISK = {"CLI_002", "CLI_006", "CLI_007"}
EXPECTED_NOT_AT_RISK = {
    "CLI_001", "CLI_003", "CLI_004", "CLI_005", "CLI_008", "CLI_009", "CLI_010",
}


def test_corpus_has_exactly_fifty_notes():
    notes = load_notes(DEFAULT_NOTES_PATH)
    assert len(notes) == 50


def test_corpus_has_ten_companies_with_five_notes_each():
    notes = load_notes(DEFAULT_NOTES_PATH)
    by_company: dict[str, int] = {}
    for note in notes:
        by_company[note["company_code"]] = by_company.get(note["company_code"], 0) + 1

    assert len(by_company) == 10
    assert all(count == 5 for count in by_company.values())


def test_corpus_note_ids_are_unique():
    notes = load_notes(DEFAULT_NOTES_PATH)
    ids = [n["note_id"] for n in notes]
    assert len(ids) == len(set(ids))


def test_ingest_real_corpus_produces_fifty_vectors(real_corpus_rag_config, fake_embeddings):
    metadata = build_index(real_corpus_rag_config, embeddings=fake_embeddings)
    assert metadata["count"] == 50

    import faiss

    index = faiss.read_index(str(real_corpus_rag_config.index_path))
    assert index.ntotal == 50


def test_source_notes_file_not_modified_by_ingestion(real_corpus_rag_config, fake_embeddings):
    before = DEFAULT_NOTES_PATH.read_text()
    build_index(real_corpus_rag_config, embeddings=fake_embeddings)
    after = DEFAULT_NOTES_PATH.read_text()
    assert before == after


def test_exhaustive_classification_returns_exactly_amazon_exxon_alphabet(
    real_corpus_rag_config, fake_embeddings
):
    build_index(real_corpus_rag_config, embeddings=fake_embeddings)
    retriever = RelationshipNotesRetriever(real_corpus_rag_config, embeddings=fake_embeddings)

    results = retriever.search(
        "which companies were recently flagged as at risk by their relationship manager?",
        date_from="2026-05-21",
        date_to="2026-08-19",
        return_all_matches=True,
    )

    returned_codes = {r["company_code"] for r in results}
    assert returned_codes == EXPECTED_AT_RISK
    assert returned_codes.isdisjoint(EXPECTED_NOT_AT_RISK)


def test_exhaustive_classification_excludes_each_non_flagged_company_by_name(
    real_corpus_rag_config, fake_embeddings
):
    build_index(real_corpus_rag_config, embeddings=fake_embeddings)
    retriever = RelationshipNotesRetriever(real_corpus_rag_config, embeddings=fake_embeddings)

    results = retriever.search(
        "at risk companies", date_from="2026-05-21", date_to="2026-08-19", return_all_matches=True
    )
    names = {r["company_name"] for r in results}

    assert names == {"Amazon", "Exxon Mobil", "Alphabet"}
    for excluded in ["Walmart", "Apple", "UnitedHealth Group", "CVS Health",
                      "McKesson", "Cencora", "Costco"]:
        assert excluded not in names


def test_exhaustive_classification_cites_newest_applicable_note(real_corpus_rag_config, fake_embeddings):
    build_index(real_corpus_rag_config, embeddings=fake_embeddings)
    retriever = RelationshipNotesRetriever(real_corpus_rag_config, embeddings=fake_embeddings)

    results = retriever.search(
        "at risk", date_from="2026-05-21", date_to="2026-08-19", return_all_matches=True
    )
    by_code = {r["company_code"]: r for r in results}

    assert by_code["CLI_002"]["note_id"] == "RMN_007"  # newest Amazon note in range
    assert by_code["CLI_006"]["note_id"] == "RMN_031"  # newest Exxon Mobil note in range
    assert by_code["CLI_007"]["note_id"] == "RMN_035"  # newest Alphabet note in range
