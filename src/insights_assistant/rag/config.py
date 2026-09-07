import os
from dataclasses import dataclass, field
from pathlib import Path

# The source corpus actually lives at src/insights_assistant/data/, not a
# repo-root data/ directory -- paths below are relative to that real location
# rather than inventing a new top-level data/ directory.
PACKAGE_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEFAULT_INDEX_DIR = PACKAGE_DATA_DIR / "indexes"

DEFAULT_NOTES_PATH = PACKAGE_DATA_DIR / "relationship_manager_notes.json"
DEFAULT_INDEX_PATH = DEFAULT_INDEX_DIR / "relationship_manager_notes.faiss"
DEFAULT_METADATA_PATH = DEFAULT_INDEX_DIR / "relationship_manager_notes.metadata.json"

DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"


@dataclass
class RagConfig:
    """Paths and embedding-model configuration shared by ingestion and retrieval.

    All paths default to the real, existing corpus location and a sibling
    indexes/ directory; every field can be overridden (tests point these at a
    temp directory).
    """

    notes_path: Path = field(default_factory=lambda: DEFAULT_NOTES_PATH)
    index_path: Path = field(default_factory=lambda: DEFAULT_INDEX_PATH)
    metadata_path: Path = field(default_factory=lambda: DEFAULT_METADATA_PATH)
    embedding_model: str = field(
        default_factory=lambda: os.environ.get("RAG_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
    )

    def __post_init__(self):
        self.notes_path = Path(self.notes_path)
        self.index_path = Path(self.index_path)
        self.metadata_path = Path(self.metadata_path)
