from datetime import datetime, timezone

import pytest

from insights_assistant.contracts.api.enums import DisplayDensity, RankingCriterion
from insights_assistant.contracts.api.preferences import UserPreferences


@pytest.fixture
def now() -> datetime:
    # Real current time, not a hardcoded literal -- see the matching comment
    # in tests/agents/conftest.py for why a fixed past date eventually
    # breaks any test that compares a manifest.deadline built from it
    # against the real wall clock.
    return datetime.now(timezone.utc)


@pytest.fixture
def preferences() -> UserPreferences:
    return UserPreferences(
        display_name="Alex Bianchi",
        role="Relationship Banker",
        default_data_domains=["credit_exposure", "relationship_interactions"],
        default_ranking_criteria=[RankingCriterion.URGENCY, RankingCriterion.CONFIDENCE],
        email_digest_enabled=True,
        at_risk_alerts_enabled=True,
        display_density=DisplayDensity.COMFORTABLE,
        default_lookback_months=24,
    )
