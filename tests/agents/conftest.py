from datetime import datetime, timezone

import pytest

from insights_assistant.contracts.api.enums import DisplayDensity, RankingCriterion
from insights_assistant.contracts.api.preferences import UserPreferences


@pytest.fixture
def now() -> datetime:
    # Real current time, not a hardcoded literal: agents/research_execution.py's
    # dispatch_and_join compares a manifest.deadline built from this fixture
    # against the REAL wall clock (datetime.now(timezone.utc)) to compute how
    # long asyncio.wait should still block -- a fixed past-tense literal here
    # eventually drifts behind the real clock as the calendar advances, making
    # every deadline look already-expired regardless of any timeout value.
    return datetime.now(timezone.utc)


@pytest.fixture
def preferences() -> UserPreferences:
    return UserPreferences(
        display_name="Alex Bianchi",
        role="Relationship Banker",
        default_data_domains=["credit_exposure", "relationship_interactions"],
        default_ranking_criteria=[RankingCriterion.URGENCY],
        email_digest_enabled=True,
        at_risk_alerts_enabled=True,
        display_density=DisplayDensity.COMFORTABLE,
        default_lookback_months=24,
    )
