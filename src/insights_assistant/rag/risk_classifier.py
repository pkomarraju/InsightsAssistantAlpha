"""Deterministic classifier distinguishing explicit relationship-level risk
statements from hard negatives -- project, implementation, opportunity,
milestone, or schedule risk that does not describe the overall client
relationship, and explicit resolutions/negations of an earlier concern.

This is intentionally rule-based rather than model-based: it only needs to
work over this corpus's phrasing, and it must be usable in tests with no LLM
or network call.
"""

import re

AT_RISK = "at_risk"
NOT_AT_RISK = "not_at_risk"
NO_SIGNAL = "no_signal"

_REL = r"(?:the |this |overall |broader |banking )*relationship"

# Checked first: an explicit negation or resolution wins even if the note
# also contains an unrelated "X is at risk" phrase (e.g. a hard-negative
# project/opportunity risk mentioned in the same note).
_NOT_AT_RISK_PATTERNS = [
    re.compile(rf"{_REL}.{{0,60}}?\b(is not|remains? not|was not|isn't)\b.{{0,20}}?at.?risk", re.I),
    re.compile(rf"\bnot\b.{{0,20}}?{_REL}.{{0,40}}?at.?risk", re.I),
    re.compile(rf"{_REL}.{{0,40}}?\bnot (currently )?(flagged|considered)\b.{{0,20}}?at.?risk", re.I),
    re.compile(r"\bno (current )?relationship[- ]level (risk|concern)", re.I),
    re.compile(r"\bno current at.?risk designation\b", re.I),
    re.compile(r"\bnot flagged at risk\b", re.I),
    re.compile(r"\bnot currently at risk\b", re.I),
    re.compile(r"no indication.{0,60}?relationship.{0,30}?at.?risk", re.I),
    re.compile(rf"{_REL}.{{0,40}}?remains? stable", re.I),
    re.compile(rf"does not (threaten|affect) the.{{0,40}}?{_REL}", re.I),
    re.compile(r"\bnot the (overall )?relationship\b", re.I),
    re.compile(r"applies to the opportunity, not the.{0,20}?relationship", re.I),
    re.compile(rf"{_REL}.{{0,20}}?remains? (strong|healthy)", re.I),
]

# Checked second: an explicit, current, relationship-level risk statement.
_AT_RISK_PATTERNS = [
    re.compile(rf"flagging.{{0,40}}?{_REL}.{{0,20}}?as at.?risk", re.I),
    re.compile(rf"{_REL}.{{0,20}}?(is|remains|now is)\b.{{0,20}}?at.?risk", re.I),
    re.compile(rf"consider.{{0,20}}?{_REL}.{{0,30}}?at.?risk", re.I),
    re.compile(rf"view.{{0,10}}?{_REL}.{{0,10}}?as at.?risk", re.I),
    re.compile(rf"{_REL}.{{0,10}}?at.?risk flag\b", re.I),
    re.compile(rf"maintain.{{0,20}}?{_REL}.{{0,10}}?at.?risk", re.I),
]


def classify_relationship_risk(note_text: str) -> str:
    """Classify a single note as AT_RISK, NOT_AT_RISK, or NO_SIGNAL.

    NOT_AT_RISK covers both an explicit negation ("the relationship is not at
    risk") and an explicit resolution of an earlier concern. NO_SIGNAL means
    the note makes no relationship-level risk claim at all (it may still
    mention project/opportunity/milestone risk -- a hard negative that must
    not be conflated with relationship risk).
    """
    for pattern in _NOT_AT_RISK_PATTERNS:
        if pattern.search(note_text):
            return NOT_AT_RISK
    for pattern in _AT_RISK_PATTERNS:
        if pattern.search(note_text):
            return AT_RISK
    return NO_SIGNAL
