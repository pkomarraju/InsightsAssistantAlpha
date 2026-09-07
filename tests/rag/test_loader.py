import json

import pytest

from insights_assistant.rag.config import DEFAULT_NOTES_PATH
from insights_assistant.rag.loader import REQUIRED_FIELDS, NoteValidationError, load_notes


def test_loads_real_corpus_file():
    notes = load_notes(DEFAULT_NOTES_PATH)
    assert len(notes) >= 1
    for note in notes:
        for field_name in REQUIRED_FIELDS:
            assert field_name in note


def test_loads_sample_notes_and_preserves_order(notes_file, sample_notes):
    notes = load_notes(notes_file)
    assert [n["note_id"] for n in notes] == [n["note_id"] for n in sample_notes]


def test_deterministic_order_matches_file_order(notes_file, sample_notes):
    first = load_notes(notes_file)
    second = load_notes(notes_file)
    assert [n["note_id"] for n in first] == [n["note_id"] for n in second]


def test_preserves_complete_original_metadata(tmp_path, sample_notes):
    sample_notes[0]["extra_field"] = "kept as-is"
    path = tmp_path / "notes.json"
    path.write_text(json.dumps(sample_notes))

    notes = load_notes(path)
    assert notes[0]["extra_field"] == "kept as-is"


def test_supports_object_with_notes_array(tmp_path, sample_notes):
    path = tmp_path / "notes.json"
    path.write_text(json.dumps({"notes": sample_notes}))

    notes = load_notes(path)
    assert len(notes) == len(sample_notes)


def test_missing_required_field_raises(tmp_path, sample_notes):
    del sample_notes[0]["relationship_manager"]
    path = tmp_path / "notes.json"
    path.write_text(json.dumps(sample_notes))

    with pytest.raises(NoteValidationError, match="relationship_manager"):
        load_notes(path)


def test_null_required_field_raises(tmp_path, sample_notes):
    sample_notes[0]["note_text"] = None
    path = tmp_path / "notes.json"
    path.write_text(json.dumps(sample_notes))

    with pytest.raises(NoteValidationError, match="note_text"):
        load_notes(path)


def test_duplicate_note_id_raises(tmp_path, sample_notes):
    sample_notes[1]["note_id"] = sample_notes[0]["note_id"]
    path = tmp_path / "notes.json"
    path.write_text(json.dumps(sample_notes))

    with pytest.raises(NoteValidationError, match="duplicate note_id"):
        load_notes(path)


def test_invalid_note_date_raises(tmp_path, sample_notes):
    sample_notes[0]["note_date"] = "07/18/2026"
    path = tmp_path / "notes.json"
    path.write_text(json.dumps(sample_notes))

    with pytest.raises(NoteValidationError, match="note_date"):
        load_notes(path)


def test_missing_file_raises(tmp_path):
    with pytest.raises(NoteValidationError, match="not found"):
        load_notes(tmp_path / "does_not_exist.json")


def test_invalid_top_level_shape_raises(tmp_path):
    path = tmp_path / "notes.json"
    path.write_text(json.dumps("just a string"))

    with pytest.raises(NoteValidationError):
        load_notes(path)


def test_does_not_silently_skip_multiple_invalid_records(tmp_path, sample_notes):
    del sample_notes[0]["note_text"]
    del sample_notes[2]["company_name"]
    path = tmp_path / "notes.json"
    path.write_text(json.dumps(sample_notes))

    with pytest.raises(NoteValidationError) as exc_info:
        load_notes(path)
    message = str(exc_info.value)
    assert "note_text" in message
    assert "company_name" in message
