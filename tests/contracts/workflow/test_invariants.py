import pytest

from insights_assistant.contracts.api.enums import EvidenceSourceAgent
from insights_assistant.contracts.workflow.enums import SourcePayloadStatus
from insights_assistant.contracts.workflow.invariants import (
    WorkflowInvariantError,
    ensure_ready_for_synthesis,
    is_manifest_ready,
    validate_single_request_version,
    validate_unique_payload_keys,
)
from insights_assistant.contracts.workflow.research import PayloadKey, ResearchManifest, SourcePayload

EXT = EvidenceSourceAgent.EXTERNAL_DATA_AGENT
INT = EvidenceSourceAgent.INTERNAL_DATA_AGENT
NOTES = EvidenceSourceAgent.RELATIONSHIP_NOTES_AGENT


def _payload(company_code="CLI_001", source_agent=EXT, request_version=1, status=SourcePayloadStatus.COMPLETED, now=None, error=None):
    return SourcePayload(
        request_id="REQ_1", request_version=request_version, company_code=company_code,
        source_agent=source_agent, status=status, error=error, started_at=now, completed_at=now,
    )


def _manifest(keys, request_version=1, now=None):
    return ResearchManifest.open(
        request_id="REQ_1", request_version=request_version, expected_payload_keys=keys, now=now
    )


class TestValidateUniquePayloadKeys:
    def test_no_duplicates_passes(self, now):
        payloads = [_payload(source_agent=EXT, now=now), _payload(source_agent=INT, now=now)]
        validate_unique_payload_keys(payloads)  # no raise

    def test_duplicate_key_raises(self, now):
        payloads = [_payload(source_agent=EXT, now=now), _payload(source_agent=EXT, now=now)]
        with pytest.raises(WorkflowInvariantError, match="duplicate SourcePayload"):
            validate_unique_payload_keys(payloads)

    def test_same_source_different_company_is_not_a_duplicate(self, now):
        payloads = [
            _payload(company_code="CLI_001", source_agent=EXT, now=now),
            _payload(company_code="CLI_002", source_agent=EXT, now=now),
        ]
        validate_unique_payload_keys(payloads)  # no raise

    def test_same_key_different_request_version_is_not_a_duplicate(self, now):
        payloads = [
            _payload(source_agent=EXT, request_version=1, now=now),
            _payload(source_agent=EXT, request_version=2, now=now),
        ]
        validate_unique_payload_keys(payloads)  # no raise


class TestValidateSingleRequestVersion:
    def test_matching_versions_pass(self, now):
        payloads = [_payload(request_version=1, now=now)]
        validate_single_request_version(payloads, "REQ_1", 1)  # no raise

    def test_mixed_versions_raise(self, now):
        payloads = [_payload(request_version=1, now=now), _payload(request_version=2, now=now)]
        with pytest.raises(WorkflowInvariantError, match="different request versions must never be mixed"):
            validate_single_request_version(payloads, "REQ_1", 1)

    def test_mismatched_request_id_raises(self, now):
        payload = SourcePayload(
            request_id="REQ_OTHER", request_version=1, company_code="CLI_001",
            source_agent=EXT, status=SourcePayloadStatus.COMPLETED, started_at=now, completed_at=now,
        )
        with pytest.raises(WorkflowInvariantError, match="does not match expected request_id"):
            validate_single_request_version([payload], "REQ_1", 1)


class TestManifestReadiness:
    def test_ready_when_all_expected_keys_completed(self, now):
        keys = [PayloadKey(company_code="CLI_001", source_agent=a) for a in (EXT, INT, NOTES)]
        manifest = _manifest(keys, now=now)
        payloads = [_payload(source_agent=a, now=now) for a in (EXT, INT, NOTES)]
        assert is_manifest_ready(manifest, payloads) is True
        ensure_ready_for_synthesis(manifest, payloads)  # no raise

    def test_not_ready_when_a_key_is_missing(self, now):
        keys = [PayloadKey(company_code="CLI_001", source_agent=a) for a in (EXT, INT, NOTES)]
        manifest = _manifest(keys, now=now)
        payloads = [_payload(source_agent=a, now=now) for a in (EXT, INT)]
        assert is_manifest_ready(manifest, payloads) is False
        with pytest.raises(WorkflowInvariantError, match="not ready for synthesis"):
            ensure_ready_for_synthesis(manifest, payloads)

    def test_not_ready_when_a_payload_failed(self, now):
        keys = [PayloadKey(company_code="CLI_001", source_agent=a) for a in (EXT, INT)]
        manifest = _manifest(keys, now=now)
        payloads = [
            _payload(source_agent=EXT, now=now),
            _payload(source_agent=INT, now=now, status=SourcePayloadStatus.FAILED, error="no data"),
        ]
        assert is_manifest_ready(manifest, payloads) is False
        with pytest.raises(WorkflowInvariantError, match="failed"):
            ensure_ready_for_synthesis(manifest, payloads)

    def test_not_ready_when_a_payload_timed_out(self, now):
        keys = [PayloadKey(company_code="CLI_001", source_agent=EXT)]
        manifest = _manifest(keys, now=now)
        payloads = [_payload(source_agent=EXT, now=now, status=SourcePayloadStatus.TIMED_OUT, error="deadline exceeded")]
        assert is_manifest_ready(manifest, payloads) is False

    def test_extra_unexpected_payload_does_not_block_readiness(self, now):
        """expected_payload_keys is the join condition; an extra completed
        payload beyond what was expected should not prevent synthesis."""
        keys = [PayloadKey(company_code="CLI_001", source_agent=EXT)]
        manifest = _manifest(keys, now=now)
        payloads = [
            _payload(source_agent=EXT, now=now),
            _payload(company_code="CLI_002", source_agent=EXT, now=now),
        ]
        assert is_manifest_ready(manifest, payloads) is True

    def test_ensure_ready_rejects_duplicate_payloads_before_checking_readiness(self, now):
        keys = [PayloadKey(company_code="CLI_001", source_agent=EXT)]
        manifest = _manifest(keys, now=now)
        payloads = [_payload(source_agent=EXT, now=now), _payload(source_agent=EXT, now=now)]
        with pytest.raises(WorkflowInvariantError, match="duplicate SourcePayload"):
            ensure_ready_for_synthesis(manifest, payloads)

    def test_ensure_ready_rejects_mixed_request_versions(self, now):
        keys = [PayloadKey(company_code="CLI_001", source_agent=EXT)]
        manifest = _manifest(keys, now=now, request_version=1)
        payloads = [_payload(source_agent=EXT, now=now, request_version=2)]
        with pytest.raises(WorkflowInvariantError, match="must never be mixed"):
            ensure_ready_for_synthesis(manifest, payloads)

    def test_readiness_blocked_until_the_last_of_multiple_companies_arrives(self, now):
        """Batch-processing semantics (requirement 9): companies and sources
        finish independently, in any order, and the Synthesizer must not be
        considered ready until the very last expected payload -- across ALL
        companies, not just one -- has arrived. Two companies x three
        sources = 6 expected keys; every proper subset must stay blocked,
        and readiness must flip to True exactly once the 6th arrives,
        regardless of which key was last."""

        keys = [
            PayloadKey(company_code=company, source_agent=source)
            for company in ("CLI_001", "CLI_002")
            for source in (EXT, INT, NOTES)
        ]
        manifest = _manifest(keys, now=now)
        all_payloads = [
            _payload(company_code=key.company_code, source_agent=key.source_agent, now=now) for key in keys
        ]

        # Every proper subset (any 5 of the 6, in any arrival order) is blocked.
        for missing_index in range(len(all_payloads)):
            partial = all_payloads[:missing_index] + all_payloads[missing_index + 1 :]
            assert is_manifest_ready(manifest, partial) is False
            with pytest.raises(WorkflowInvariantError, match="not ready for synthesis"):
                ensure_ready_for_synthesis(manifest, partial)

        # Full set is ready regardless of arrival order.
        assert is_manifest_ready(manifest, all_payloads) is True
        assert is_manifest_ready(manifest, list(reversed(all_payloads))) is True
        ensure_ready_for_synthesis(manifest, all_payloads)  # no raise

    def test_isolation_between_request_ids_and_versions_at_readiness_check(self, now):
        """Never mix payloads across request IDs or request versions
        (requirement 5) -- a complete set for the wrong request_id/version
        must not satisfy this manifest's readiness."""

        keys = [PayloadKey(company_code="CLI_001", source_agent=a) for a in (EXT, INT)]
        manifest = _manifest(keys, now=now, request_version=1)

        wrong_version_payloads = [
            _payload(source_agent=a, now=now, request_version=2) for a in (EXT, INT)
        ]
        with pytest.raises(WorkflowInvariantError, match="must never be mixed"):
            ensure_ready_for_synthesis(manifest, wrong_version_payloads)

        wrong_request_payload = SourcePayload(
            request_id="REQ_OTHER", request_version=1, company_code="CLI_001",
            source_agent=EXT, status=SourcePayloadStatus.COMPLETED, started_at=now, completed_at=now,
        )
        with pytest.raises(WorkflowInvariantError, match="does not match expected request_id"):
            ensure_ready_for_synthesis(manifest, [wrong_request_payload, _payload(source_agent=INT, now=now)])
