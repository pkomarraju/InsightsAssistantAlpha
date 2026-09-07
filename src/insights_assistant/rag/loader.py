import copy
import json
from datetime import date
from pathlib import Path

REQUIRED_FIELDS = [
    "note_id",
    "company_code",
    "company_name",
    "relationship_manager",
    "note_date",
    "note_text",
    "source_type",
    "synthetic",
]


class NoteValidationError(ValueError):
    """Raised when the notes corpus is missing required fields or is otherwise malformed."""


def _extract_records(payload) -> list:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("notes"), list):
        return payload["notes"]
    raise NoteValidationError(
        "Notes file must be a JSON array of notes, or an object with a top-level "
        "'notes' array; got " + type(payload).__name__
    )


def _validate_record(record, index: int) -> list[str]:
    errors = []
    if not isinstance(record, dict):
        return [f"record at index {index} is not a JSON object"]

    for field_name in REQUIRED_FIELDS:
        if field_name not in record:
            errors.append(f"record at index {index} is missing required field '{field_name}'")
        elif record[field_name] is None:
            errors.append(f"record at index {index} has null value for required field '{field_name}'")
        elif isinstance(record[field_name], str) and record[field_name].strip() == "":
            errors.append(f"record at index {index} has empty value for required field '{field_name}'")

    if "note_date" in record and isinstance(record["note_date"], str) and record["note_date"].strip():
        try:
            date.fromisoformat(record["note_date"])
        except ValueError:
            errors.append(
                f"record at index {index} (note_id={record.get('note_id')!r}) has invalid "
                f"note_date {record['note_date']!r}; expected ISO YYYY-MM-DD"
            )

    return errors


def load_notes(path: Path) -> list[dict]:
    """Load, validate, and return the relationship-manager notes corpus.

    Returns records sorted deterministically by note_id (the stable identity
    for each document), each preserving the complete original metadata (not
    trimmed to REQUIRED_FIELDS). Raises NoteValidationError with every problem
    found -- it does not silently skip invalid records.
    """
    path = Path(path)
    if not path.exists():
        raise NoteValidationError(f"Notes file not found: {path}")

    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise NoteValidationError(f"Notes file {path} is not valid JSON: {e}") from e

    records = _extract_records(payload)

    all_errors: list[str] = []
    seen_ids: dict[str, int] = {}
    for i, record in enumerate(records):
        all_errors.extend(_validate_record(record, i))
        if isinstance(record, dict) and "note_id" in record and record["note_id"] is not None:
            note_id = record["note_id"]
            if note_id in seen_ids:
                all_errors.append(
                    f"duplicate note_id {note_id!r} at indices {seen_ids[note_id]} and {i}"
                )
            else:
                seen_ids[note_id] = i

    if all_errors:
        raise NoteValidationError(
            f"{len(all_errors)} problem(s) found in {path}:\n  - " + "\n  - ".join(all_errors)
        )

    # Deterministic order: sort by note_id (the stable identity for each
    # document) rather than relying on file order.
    ordered = sorted(records, key=lambda record: record["note_id"])
    return [copy.deepcopy(record) for record in ordered]
