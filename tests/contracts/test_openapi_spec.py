"""Structural validation of docs/api/openapi.yaml, and a drift check that
every Python enum in insights_assistant.contracts.api.enums has exactly the
same value set as its counterpart in the OpenAPI spec.
"""

from pathlib import Path

import pytest
import yaml
from openapi_spec_validator import validate

from insights_assistant.contracts.api import enums
from insights_assistant.contracts.workflow.enums import ReviewDecisionType

SPEC_PATH = Path(__file__).parents[2] / "docs" / "api" / "openapi.yaml"


@pytest.fixture(scope="module")
def spec() -> dict:
    return yaml.safe_load(SPEC_PATH.read_text())


def test_openapi_spec_is_valid(spec):
    """Validates against the OpenAPI 3.1 meta-schema (stronger than a lint pass)."""
    validate(spec)


def test_openapi_spec_has_the_nine_contract_groups_plus_reset_and_cancel(spec):
    paths = spec["paths"]
    assert set(paths) == {
        "/v1/metadata",
        "/v1/preferences",
        "/v1/requests",
        "/v1/requests/{requestId}",
        "/v1/requests/{requestId}/cancel",
        "/v1/insights",
        "/v1/insights/{insightId}",
        "/v1/insights/{insightId}/approve",
        "/v1/insights/{insightId}/reject",
        "/v1/insights/{insightId}/reset",
    }


# Maps each OpenAPI component schema name to the Python enum that must have
# an identical value set. Add a pair here whenever a new enum is introduced.
#
# RequestStage is deliberately NOT here: it's a coarser, hand-designed
# display vocabulary that folds two internal WorkflowStage values together
# (see the schema's own description in openapi.yaml and
# api/server.py::_STAGE_DISPLAY_MAP) and adds `queued`, which has no
# WorkflowStage counterpart at all. Its value SET is intentionally not
# identical to WorkflowStage's, so a drift check here would be wrong, not
# protective.
ENUM_SCHEMA_PAIRS = [
    ("RelationshipTier", enums.RelationshipTier),
    ("InsightCategory", enums.InsightCategory),
    ("InsightSubtype", enums.InsightSubtype),
    ("InsightPriority", enums.InsightPriority),
    ("InsightPersona", enums.InsightPersona),
    ("ReviewStatus", enums.ReviewStatus),
    ("RejectReason", enums.RejectReason),
    ("EvidenceSourceAgent", enums.EvidenceSourceAgent),
    ("EvidenceSourceType", enums.EvidenceSourceType),
    ("RequestStatus", enums.RequestStatus),
    ("SourceAgentStatus", enums.SourceAgentStatus),
    ("CompanySelectionMode", enums.CompanySelectionMode),
    ("RankingCriterion", enums.RankingCriterion),
    ("InsightSortField", enums.InsightSortField),
    ("RequestSortField", enums.RequestSortField),
    ("SortDirection", enums.SortDirection),
    ("DisplayDensity", enums.DisplayDensity),
    ("ReviewDecisionType", ReviewDecisionType),
]


@pytest.mark.parametrize("schema_name,py_enum", ENUM_SCHEMA_PAIRS, ids=[p[0] for p in ENUM_SCHEMA_PAIRS])
def test_enum_values_match_openapi_schema(spec, schema_name, py_enum):
    openapi_values = set(spec["components"]["schemas"][schema_name]["enum"])
    python_values = {member.value for member in py_enum}
    assert python_values == openapi_values, (
        f"{schema_name}: OpenAPI has {openapi_values!r}, Python enum {py_enum.__name__} has {python_values!r}"
    )


def test_error_code_enum_matches(spec):
    openapi_values = set(spec["components"]["schemas"]["ErrorResponse"]["properties"]["error"]["properties"]["code"]["enum"])
    python_values = {member.value for member in enums.ErrorCode}
    assert python_values == openapi_values


def test_filing_type_enum_matches(spec):
    openapi_values = set(spec["components"]["schemas"]["Metadata"]["properties"]["filingTypes"]["items"]["enum"])
    python_values = {member.value for member in enums.FilingType}
    assert python_values == openapi_values


def test_confidence_tier_id_enum_matches(spec):
    openapi_values = set(spec["components"]["schemas"]["ConfidenceTierOption"]["properties"]["id"]["enum"])
    python_values = {member.value for member in enums.ConfidenceTierId}
    assert python_values == openapi_values


def test_review_event_action_enum_matches(spec):
    openapi_values = set(spec["components"]["schemas"]["ReviewEvent"]["properties"]["action"]["enum"])
    python_values = {member.value for member in enums.ReviewEventAction}
    assert python_values == openapi_values
