from datetime import timedelta

import pytest
from pydantic import ValidationError

from insights_assistant.contracts.api.enums import EvidenceSourceAgent
from insights_assistant.contracts.api.requests import ExternalResearchSelection, InternalResearchSelection
from insights_assistant.contracts.workflow.config import INSIGHTS_SOURCE_EXECUTION_TIMEOUT_SECONDS
from insights_assistant.contracts.workflow.enums import SourcePayloadStatus
from insights_assistant.contracts.workflow.research import PayloadKey, ResearchManifest, ResearchTask, SourcePayload, required_sources

EXT = EvidenceSourceAgent.EXTERNAL_DATA_AGENT
INT = EvidenceSourceAgent.INTERNAL_DATA_AGENT
NOTES = EvidenceSourceAgent.RELATIONSHIP_NOTES_AGENT


def _external(enabled: bool) -> ExternalResearchSelection:
    return ExternalResearchSelection(edgar_enabled=enabled, filing_types=["10-K"], lookback_months=24)


def _internal(domain_ids: list[str]) -> InternalResearchSelection:
    return InternalResearchSelection(
        data_domain_ids=domain_ids or ["client_profitability"],
        general_search_prompt="x" * 20,
    )


class TestRequiredSources:
    def test_edgar_disabled_no_external(self):
        assert EXT not in required_sources(_external(False), _internal(["credit_exposure"]))

    def test_edgar_enabled_adds_external(self):
        assert EXT in required_sources(_external(True), _internal(["credit_exposure"]))

    def test_structured_domain_adds_internal(self):
        result = required_sources(_external(False), _internal(["credit_exposure"]))
        assert result == {INT}

    def test_relationship_interactions_adds_notes_not_internal(self):
        result = required_sources(_external(False), InternalResearchSelection(
            data_domain_ids=["relationship_interactions"], general_search_prompt="x" * 20
        ))
        assert result == {NOTES}

    def test_mixed_domains_add_both_internal_and_notes(self):
        result = required_sources(_external(False), InternalResearchSelection(
            data_domain_ids=["credit_exposure", "relationship_interactions"], general_search_prompt="x" * 20
        ))
        assert result == {INT, NOTES}

    def test_all_three_enabled(self):
        result = required_sources(_external(True), InternalResearchSelection(
            data_domain_ids=["product_whitespace", "relationship_interactions"], general_search_prompt="x" * 20
        ))
        assert result == {EXT, INT, NOTES}

    def test_never_waits_on_disabled_edgar_even_with_internal_enabled(self):
        result = required_sources(_external(False), _internal(["capital_markets_advisory"]))
        assert EXT not in result

    def test_new_provider_neutral_shape_without_edgar_enabled(self):
        """The new, non-deprecated shape: enabled/providers, no edgar_enabled at all."""
        selection = ExternalResearchSelection(
            enabled=True, providers=["fmp", "alpha_vantage"], lookback_months=24
        )
        assert EXT in required_sources(selection, _internal(["credit_exposure"]))
        assert selection.providers == ["fmp", "alpha_vantage"]

    def test_enabled_true_defaults_providers_to_all_three_when_omitted(self):
        selection = ExternalResearchSelection(enabled=True, lookback_months=24)
        assert selection.providers == ["fmp", "alpha_vantage", "fred"]

    def test_enabled_takes_precedence_over_deprecated_edgar_enabled(self):
        """An explicit enabled always wins, even when the deprecated field disagrees --
        legacy compatibility is a fallback, not an override."""
        selection = ExternalResearchSelection(edgar_enabled=True, enabled=False, lookback_months=24)
        assert selection.enabled is False
        assert EXT not in required_sources(selection, _internal(["credit_exposure"]))

    def test_missing_both_enabled_and_edgar_enabled_is_rejected(self):
        with pytest.raises(ValidationError):
            ExternalResearchSelection(lookback_months=24)

    def test_all_structured_domains_recognized(self):
        domains = [
            "client_profitability", "credit_exposure", "deposits_treasury_payments",
            "capital_markets_advisory", "product_whitespace",
        ]
        result = required_sources(_external(False), InternalResearchSelection(
            data_domain_ids=domains, general_search_prompt="x" * 20
        ))
        assert result == {INT}


class TestResearchTask:
    def test_valid_task(self, now, preferences):
        task = ResearchTask(
            request_id="REQ_1",
            request_version=1,
            company_code="CLI_001",
            source_agent=EXT,
            prompt="Research Walmart's latest 10-K.",
            original_user_prompt="What changed for Walmart recently?",
            preferences=preferences,
            created_at=now,
        )
        assert task.request_version == 1

    def test_invalid_company_code_rejected(self, now, preferences):
        with pytest.raises(ValidationError):
            ResearchTask(
                request_id="REQ_1", request_version=1, company_code="Walmart",
                source_agent=EXT, prompt="p", original_user_prompt="p",
                preferences=preferences, created_at=now,
            )

    def test_key_matches_company_and_source(self, now, preferences):
        task = ResearchTask(
            request_id="REQ_1", request_version=1, company_code="CLI_001",
            source_agent=EXT, prompt="p", original_user_prompt="p",
            preferences=preferences, created_at=now,
        )
        assert task.key == PayloadKey(company_code="CLI_001", source_agent=EXT)

    def test_request_version_must_be_at_least_one(self, now, preferences):
        with pytest.raises(ValidationError):
            ResearchTask(
                request_id="REQ_1", request_version=0, company_code="CLI_001",
                source_agent=EXT, prompt="p", original_user_prompt="p",
                preferences=preferences, created_at=now,
            )


class TestSourcePayload:
    def test_completed_payload_requires_null_error(self, now):
        with pytest.raises(ValidationError, match="error must be null"):
            SourcePayload(
                request_id="REQ_1", request_version=1, company_code="CLI_001",
                source_agent=EXT, status=SourcePayloadStatus.COMPLETED, error="oops",
                started_at=now, completed_at=now,
            )

    def test_failed_payload_requires_error(self, now):
        with pytest.raises(ValidationError, match="error is required"):
            SourcePayload(
                request_id="REQ_1", request_version=1, company_code="CLI_001",
                source_agent=EXT, status=SourcePayloadStatus.FAILED, error=None,
                started_at=now, completed_at=now,
            )

    def test_timed_out_payload_requires_error(self, now):
        with pytest.raises(ValidationError, match="error is required"):
            SourcePayload(
                request_id="REQ_1", request_version=1, company_code="CLI_001",
                source_agent=EXT, status=SourcePayloadStatus.TIMED_OUT, error=None,
                started_at=now, completed_at=now,
            )

    def test_completed_at_before_started_at_rejected(self, now):
        with pytest.raises(ValidationError, match="completed_at must not be before"):
            SourcePayload(
                request_id="REQ_1", request_version=1, company_code="CLI_001",
                source_agent=EXT, status=SourcePayloadStatus.COMPLETED,
                started_at=now, completed_at=now - timedelta(minutes=1),
            )

    def test_valid_completed_payload(self, now):
        payload = SourcePayload(
            request_id="REQ_1", request_version=1, company_code="CLI_001",
            source_agent=EXT, status=SourcePayloadStatus.COMPLETED,
            started_at=now, completed_at=now + timedelta(seconds=5),
        )
        assert payload.key == PayloadKey(company_code="CLI_001", source_agent=EXT)

    def test_valid_failed_payload_with_error(self, now):
        payload = SourcePayload(
            request_id="REQ_1", request_version=1, company_code="CLI_001",
            source_agent=EXT, status=SourcePayloadStatus.FAILED, error="rate limited",
            started_at=now, completed_at=now,
        )
        assert payload.status == SourcePayloadStatus.FAILED


class TestResearchManifest:
    def test_open_default_timeout_is_one_execution_timeout(self, now):
        """The bare default only covers a single-task manifest -- the real
        production call site (research_execution.build_manifest_and_tasks)
        always computes and passes an explicit, task-count-aware value via
        compute_research_workflow_timeout_seconds instead of relying on
        this default."""
        keys = [PayloadKey(company_code="CLI_001", source_agent=EXT)]
        manifest = ResearchManifest.open(
            request_id="REQ_1", request_version=1, expected_payload_keys=keys, now=now
        )
        assert manifest.deadline == now + timedelta(seconds=INSIGHTS_SOURCE_EXECUTION_TIMEOUT_SECONDS)

    def test_open_respects_explicit_timeout_override(self, now):
        keys = [PayloadKey(company_code="CLI_001", source_agent=EXT)]
        manifest = ResearchManifest.open(
            request_id="REQ_1", request_version=1, expected_payload_keys=keys, now=now, timeout_seconds=30
        )
        assert manifest.deadline == now + timedelta(seconds=30)

    def test_requires_at_least_one_expected_key(self, now):
        with pytest.raises(ValidationError):
            ResearchManifest(request_id="REQ_1", request_version=1, expected_payload_keys=[], deadline=now)
