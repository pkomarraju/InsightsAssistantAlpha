import json

import insights_assistant.mcp_servers.relationship_notes_server as server_module
from insights_assistant.rag.ingest_relationship_notes import build_index
from insights_assistant.rag.retriever import RelationshipNotesRetriever


def _reset_retriever_singleton():
    server_module._retriever = None


def test_search_tool_returns_expected_json_shape(rag_config, fake_embeddings, monkeypatch):
    build_index(rag_config, embeddings=fake_embeddings)
    _reset_retriever_singleton()
    monkeypatch.setattr(
        server_module,
        "_get_retriever",
        lambda: RelationshipNotesRetriever(rag_config, embeddings=fake_embeddings),
    )

    raw = server_module.search_relationship_notes(query="at risk competitor pricing", max_results=4)
    payload = json.loads(raw)

    assert set(payload.keys()) == {"query", "filters", "result_count", "results"}
    assert payload["query"] == "at risk competitor pricing"
    assert set(payload["filters"].keys()) == {"date_from", "date_to", "company_codes"}
    assert payload["result_count"] == len(payload["results"])
    assert payload["result_count"] == 4

    result_fields = {
        "note_id", "company_code", "company_name", "relationship_manager",
        "note_date", "note_text", "source_type", "similarity",
    }
    for row in payload["results"]:
        assert set(row.keys()) == result_fields


def test_search_tool_applies_filters_and_echoes_them(rag_config, fake_embeddings, monkeypatch):
    build_index(rag_config, embeddings=fake_embeddings)
    _reset_retriever_singleton()
    monkeypatch.setattr(
        server_module,
        "_get_retriever",
        lambda: RelationshipNotesRetriever(rag_config, embeddings=fake_embeddings),
    )

    raw = server_module.search_relationship_notes(
        query="relationship",
        date_from="2026-07-20",
        date_to="2026-07-25",
        company_codes=["CLI_006"],
        max_results=10,
    )
    payload = json.loads(raw)

    assert payload["filters"] == {
        "date_from": "2026-07-20",
        "date_to": "2026-07-25",
        "company_codes": ["CLI_006"],
    }
    assert payload["result_count"] == 1
    assert payload["results"][0]["company_code"] == "CLI_006"


def test_search_tool_returns_error_payload_when_index_missing(rag_config, monkeypatch):
    _reset_retriever_singleton()

    def _raise():
        raise server_module.RetrieverError("FAISS index not found")

    monkeypatch.setattr(server_module, "_get_retriever", _raise)

    raw = server_module.search_relationship_notes(query="anything")
    payload = json.loads(raw)

    assert payload["result_count"] == 0
    assert payload["results"] == []
    assert "error" in payload
