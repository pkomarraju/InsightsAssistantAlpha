"""FAISS-backed retriever for relationship-manager notes."""

import json
from datetime import date

import faiss
import numpy as np
from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings

from insights_assistant.rag.config import RagConfig
from insights_assistant.rag.risk_classifier import AT_RISK, classify_relationship_risk

load_dotenv()

RESULT_FIELDS = [
    "note_id",
    "company_code",
    "company_name",
    "relationship_manager",
    "note_date",
    "note_text",
    "source_type",
]


class RetrieverError(RuntimeError):
    """Base class for retriever setup/consistency errors."""


class IndexNotFoundError(RetrieverError):
    pass


class MetadataNotFoundError(RetrieverError):
    pass


class IndexMetadataMismatchError(RetrieverError):
    pass


class EmbeddingModelMismatchError(RetrieverError):
    pass


class EmbeddingDimensionMismatchError(RetrieverError):
    pass


def _parse_date(value: str, label: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as e:
        raise ValueError(f"{label} must be an ISO YYYY-MM-DD date, got {value!r}") from e


class RelationshipNotesRetriever:
    def __init__(self, config: RagConfig | None = None, embeddings=None):
        self.config = config or RagConfig()

        if not self.config.index_path.exists():
            raise IndexNotFoundError(f"FAISS index not found at {self.config.index_path}")
        if not self.config.metadata_path.exists():
            raise MetadataNotFoundError(f"Metadata file not found at {self.config.metadata_path}")

        self.index = faiss.read_index(str(self.config.index_path))
        self.metadata = json.loads(self.config.metadata_path.read_text())
        self.records: list[dict] = self.metadata["records"]

        if self.index.ntotal != len(self.records):
            raise IndexMetadataMismatchError(
                f"FAISS index has {self.index.ntotal} vectors but metadata has "
                f"{len(self.records)} records ({self.config.index_path} vs {self.config.metadata_path})"
            )

        self.dimension = self.metadata["dimension"]
        if self.index.d != self.dimension:
            raise IndexMetadataMismatchError(
                f"FAISS index dimension {self.index.d} does not match metadata dimension {self.dimension}"
            )

        self.embedding_model = self.metadata["embedding_model"]

        if embeddings is not None:
            embeddings_model = getattr(embeddings, "model", None)
            if embeddings_model is not None and embeddings_model != self.embedding_model:
                raise EmbeddingModelMismatchError(
                    f"Retriever was given an embeddings client for model {embeddings_model!r}, "
                    f"but the index was built with {self.embedding_model!r}"
                )
            self.embeddings = embeddings
        else:
            self.embeddings = OpenAIEmbeddings(model=self.embedding_model)

    def _scored_candidates(
        self,
        query: str,
        parsed_from: date | None,
        parsed_to: date | None,
        code_filter: set[str] | None,
    ) -> list[dict]:
        query_vector = np.array([self.embeddings.embed_query(query)], dtype=np.float32)
        if query_vector.shape[1] != self.dimension:
            raise EmbeddingDimensionMismatchError(
                f"Query embedding has dimension {query_vector.shape[1]}, "
                f"index expects {self.dimension}"
            )
        faiss.normalize_L2(query_vector)

        # Small synthetic corpus: search every indexed vector, then filter,
        # rather than trusting a small top_k to be exhaustive under filters.
        # FAISS has no native date/company filtering, so this is the only way
        # to avoid losing valid matches to a too-small top_k.
        k = max(self.index.ntotal, 1)
        similarities, positions = self.index.search(query_vector, k)

        candidates = []
        for similarity, position in zip(similarities[0], positions[0]):
            if position < 0:
                continue
            record = self.records[position]

            if code_filter is not None and record["company_code"] not in code_filter:
                continue
            note_date = date.fromisoformat(record["note_date"])
            if parsed_from is not None and note_date < parsed_from:
                continue
            if parsed_to is not None and note_date > parsed_to:
                continue

            result = {field_name: record[field_name] for field_name in RESULT_FIELDS}
            result["similarity"] = float(similarity)
            candidates.append(result)

        return candidates

    @staticmethod
    def _sort_results(rows: list[dict]) -> list[dict]:
        # Stable sort applied in reverse priority order: note_id asc, then
        # note_date desc, then similarity desc ends up primary.
        rows = sorted(rows, key=lambda r: r["note_id"])
        rows.sort(key=lambda r: r["note_date"], reverse=True)
        rows.sort(key=lambda r: r["similarity"], reverse=True)
        return rows

    def _exhaustive_at_risk_companies(self, candidates: list[dict]) -> list[dict]:
        """Group candidates by company, keep each company's newest applicable
        note, and keep only companies whose newest note explicitly supports a
        current relationship-level at-risk designation. Similarity is used only
        to order the qualifying companies, never to decide which are considered.
        """
        newest_by_company: dict[str, dict] = {}
        for row in candidates:
            code = row["company_code"]
            current = newest_by_company.get(code)
            if current is None or (row["note_date"], row["note_id"]) > (current["note_date"], current["note_id"]):
                newest_by_company[code] = row

        at_risk_rows = [
            row for row in newest_by_company.values()
            if classify_relationship_risk(row["note_text"]) == AT_RISK
        ]
        return self._sort_results(at_risk_rows)

    def search(
        self,
        query: str,
        date_from: str | None = None,
        date_to: str | None = None,
        company_codes: list[str] | None = None,
        max_results: int = 50,
        return_all_matches: bool = False,
    ) -> list[dict]:
        """Semantic search over the notes, with optional date/company filters.

        If `return_all_matches` is True, this switches to exhaustive
        relationship-risk classification: every note in range is retrieved
        (not limited by max_results), grouped by company_code, and only
        companies whose *newest applicable* note explicitly states a current
        relationship-level at-risk designation are returned -- one row per
        qualifying company. Similarity still ranks the output but never
        limits which companies are considered, since a small top_k is not
        guaranteed to be exhaustive under filters.
        """
        parsed_from = _parse_date(date_from, "date_from") if date_from else None
        parsed_to = _parse_date(date_to, "date_to") if date_to else None
        code_filter = set(company_codes) if company_codes else None

        if code_filter is not None:
            # company_codes does exact matching only (no ticker/name fuzzing) --
            # a caller that passes a ticker or an invented code would otherwise
            # match nothing and silently look identical to "no notes exist",
            # which is exactly what caused relationship_notes_agent to report a
            # false negative for a company whose notes were present but keyed
            # by a code the caller never actually held (see REQ_1008). Fail
            # loudly instead so the caller corrects the identifier rather than
            # reporting an unqualified "no notes found".
            known_codes = {record["company_code"] for record in self.records}
            unknown = code_filter - known_codes
            if unknown:
                raise ValueError(
                    f"company_codes contains unrecognized code(s) {sorted(unknown)!r} -- "
                    "company_codes must be the exact internal code (format CLI_xxx), never a ticker "
                    "or company name. Omit company_codes to search by semantic query alone."
                )

        candidates = self._scored_candidates(query, parsed_from, parsed_to, code_filter)

        if return_all_matches:
            return self._exhaustive_at_risk_companies(candidates)

        return self._sort_results(candidates)[:max_results]
