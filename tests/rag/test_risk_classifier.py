"""Tests for the relationship-risk vs. hard-negative classifier, exercised
against the real corpus text so they track the actual notes rather than
paraphrased copies that could drift from the source file.
"""

import pytest

from insights_assistant.rag.config import DEFAULT_NOTES_PATH
from insights_assistant.rag.loader import load_notes
from insights_assistant.rag.risk_classifier import (
    AT_RISK,
    NOT_AT_RISK,
    NO_SIGNAL,
    classify_relationship_risk,
)


@pytest.fixture
def notes_by_id():
    return {n["note_id"]: n for n in load_notes(DEFAULT_NOTES_PATH)}


# Explicit, current, relationship-level at-risk statements.
@pytest.mark.parametrize("note_id", ["RMN_001", "RMN_002", "RMN_003", "RMN_006", "RMN_007",
                                      "RMN_030", "RMN_031", "RMN_034", "RMN_035"])
def test_explicit_relationship_risk_classified_at_risk(notes_by_id, note_id):
    assert classify_relationship_risk(notes_by_id[note_id]["note_text"]) == AT_RISK


# Hard negatives: something else (project/implementation/opportunity/milestone/
# schedule) is "at risk," but the note explicitly says the relationship itself
# is not -- must NOT classify as AT_RISK.
@pytest.mark.parametrize(
    "note_id,description",
    [
        ("RMN_005", "payments migration schedule at risk, relationship stable"),
        ("RMN_014", "implementation milestone at risk, does not threaten relationship"),
        ("RMN_026", "opportunity at risk of slipping, relationship stable"),
        ("RMN_029", "trade-finance implementation timeline at risk, relationship stable"),
        ("RMN_033", "integration milestone at risk, does not affect relationship"),
        ("RMN_039", "pilot launch date at risk, confidence in relationship reaffirmed"),
        ("RMN_044", "trade-finance opportunity at risk of delay, relationship stable"),
        ("RMN_049", "discovery timeline at risk, applies to opportunity not relationship"),
    ],
)
def test_project_and_opportunity_hard_negatives_not_at_risk(notes_by_id, note_id, description):
    assert classify_relationship_risk(notes_by_id[note_id]["note_text"]) != AT_RISK


def test_explicit_not_at_risk_statement(notes_by_id):
    # "I see no current relationship-level risk flag."
    assert classify_relationship_risk(notes_by_id["RMN_027"]["note_text"]) == NOT_AT_RISK


def test_explicit_relationship_not_at_risk_wording(notes_by_id):
    # "...so the relationship is not at risk."
    assert classify_relationship_risk(notes_by_id["RMN_047"]["note_text"]) == NOT_AT_RISK


def test_purely_positive_note_has_no_risk_signal(notes_by_id):
    # No risk language of any kind.
    assert classify_relationship_risk(notes_by_id["RMN_008"]["note_text"]) == NO_SIGNAL


def test_no_indication_negation_phrasing(notes_by_id):
    # "...with no indication that the relationship is at risk."
    assert classify_relationship_risk(notes_by_id["RMN_042"]["note_text"]) == NOT_AT_RISK


def test_older_concern_superseded_by_newer_resolution_note(notes_by_id):
    # Walmart: RMN_011 raises a conditional/hypothetical concern; RMN_012 (later)
    # explicitly resolves it. The newer note must win and must not read as at-risk.
    older = notes_by_id["RMN_011"]
    newer = notes_by_id["RMN_012"]
    assert older["note_date"] < newer["note_date"]
    assert classify_relationship_risk(newer["note_text"]) == NOT_AT_RISK
    assert classify_relationship_risk(older["note_text"]) != AT_RISK
