"""Covers agents/package_store.py: the JSON review-snapshot writer. Always
redirects INSIGHTS_PACKAGES_DIR to a pytest tmp_path -- never touches the
real repo-root insight_packages/ directory.
"""

import json

import pytest

import insights_assistant.agents.package_store as package_store
from insights_assistant.contracts.api.enums import (
    ClaimType,
    EvidenceSourceAgent,
    InsightCategory,
    InsightPersona,
    InsightPriority,
    InsightSubtype,
)
from insights_assistant.contracts.api.evidence import BusinessImpact, EvidenceItem
from insights_assistant.contracts.workflow.enums import ReviewDecisionType, SourcePayloadStatus
from insights_assistant.contracts.workflow.packages import InsightPackage, RankedInsight
from insights_assistant.contracts.workflow.research import PayloadKey, SourcePayload
from insights_assistant.contracts.workflow.review import ReviewDecision

INT = EvidenceSourceAgent.INTERNAL_DATA_AGENT


@pytest.fixture(autouse=True)
def _redirect_packages_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(package_store, "INSIGHTS_PACKAGES_DIR", tmp_path / "insight_packages")
    return tmp_path / "insight_packages"


def _payload(now, *, company_code="CLI_006", source_agent=INT) -> SourcePayload:
    return SourcePayload(
        request_id="REQ_1005", request_version=1, company_code=company_code, source_agent=source_agent,
        status=SourcePayloadStatus.COMPLETED,
        evidence=[
            EvidenceItem(
                id="EV_1", source_agent=source_agent, source_type="internal", evidence_code="RISK_048",
                label="Risk assessment", detail="Relationship risk score worsening this quarter.",
                date="2026-07-01",
            )
        ],
        findings="Relationship risk score climbed this quarter.", started_at=now, completed_at=now,
    )


def _package(now, preferences, *, request_version=1, package_version=1) -> InsightPackage:
    insight = RankedInsight(
        insight_id="PKG_REQ_1005_1_INS_0", rank=1, company_code="CLI_006",
        category=InsightCategory.RELATIONSHIP_RISK, subtype=InsightSubtype.RELATIONSHIP_RISK,
        primary_claim=ClaimType.RELATIONSHIP_RISK_WORSENING,
        persona=InsightPersona.RELATIONSHIP_MANAGER, priority=InsightPriority.HIGH,
        title="Worsening relationship position", finding="Relationship risk score rose this quarter.",
        why_it_matters="Share of wallet may deteriorate.", recommended_action="Escalate to executive sponsor.",
        confidence=70, confidence_rationale="One corroborating structured metric.",
        business_impact=BusinessImpact(exposure_usd=10_100_000, description="Credit exposure"),
        evidence=[
            EvidenceItem(
                id="EV_1", source_agent=INT, source_type="internal", evidence_code="RISK_048",
                label="Risk assessment", detail="Relationship risk score worsening this quarter.",
                date="2026-07-01",
            )
        ],
    )
    return InsightPackage(
        request_id="REQ_1005", request_version=request_version, package_version=package_version,
        original_user_prompt="What changed for Exxon Mobil?", effective_research_prompt="Research Exxon Mobil.",
        preferences=preferences, source_payload_refs=[PayloadKey(company_code="CLI_006", source_agent=INT)],
        insights=[insight], unmet_requirements=[], created_at=now,
    )


def _pass_decision(package, now) -> ReviewDecision:
    return ReviewDecision(
        decision=ReviewDecisionType.PASS, request_id=package.request_id, request_version=package.request_version,
        package_version=package.package_version, comments="Well supported.", created_at=now,
    )


class TestSavePackageSnapshot:
    def test_writes_to_request_id_folder_with_version_named_file(self, now, preferences, _redirect_packages_dir):
        package = _package(now, preferences)
        decision = _pass_decision(package, now)

        path = package_store.save_package_snapshot(package, [_payload(now)], decision)

        assert path is not None
        assert path == _redirect_packages_dir / "REQ_1005" / "rv1_pv1.json"
        assert path.exists()

    def test_different_package_versions_produce_separate_files(self, now, preferences, _redirect_packages_dir):
        first = _package(now, preferences, package_version=1)
        second = _package(now, preferences, package_version=2)

        path1 = package_store.save_package_snapshot(first, [_payload(now)], _pass_decision(first, now))
        path2 = package_store.save_package_snapshot(second, [_payload(now)], _pass_decision(second, now))

        assert path1 != path2
        assert path1.parent == path2.parent  # same request_id folder
        assert {p.name for p in path1.parent.iterdir()} == {"rv1_pv1.json", "rv1_pv2.json"}

    def test_snapshot_content_includes_input_and_output_and_review_decision(
        self, now, preferences, _redirect_packages_dir
    ):
        package = _package(now, preferences)
        payload = _payload(now)
        decision = _pass_decision(package, now)

        path = package_store.save_package_snapshot(package, [payload], decision)
        content = json.loads(path.read_text())

        assert content["requestId"] == "REQ_1005"
        assert content["requestVersion"] == 1
        assert content["packageVersion"] == 1
        assert content["originalUserPrompt"] == "What changed for Exxon Mobil?"

        # Input: the raw research payload, findings, and evidence.
        assert len(content["sourcePayloads"]) == 1
        assert content["sourcePayloads"][0]["companyCode"] == "CLI_006"
        assert content["sourcePayloads"][0]["evidence"][0]["evidenceCode"] == "RISK_048"

        # Output: the synthesized insight.
        assert len(content["insights"]) == 1
        assert content["insights"][0]["title"] == "Worsening relationship position"
        assert content["insights"][0]["category"] == "relationship_risk"
        assert content["insights"][0]["businessImpact"]["exposureUsd"] == 10_100_000

        # What the Reviewer decided about this exact package.
        assert content["reviewDecision"]["decision"] == "pass"

    def test_write_failure_is_swallowed_not_raised(self, now, preferences, monkeypatch, _redirect_packages_dir):
        """A filesystem error must never propagate into the workflow --
        this is a best-effort review aid, not a critical dependency."""
        package = _package(now, preferences)

        def _boom(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(package_store.Path, "mkdir", _boom)

        result = package_store.save_package_snapshot(package, [_payload(now)], _pass_decision(package, now))

        assert result is None

    def test_packages_dir_overridable_via_env_var(self, tmp_path, monkeypatch):
        """Mirrors contracts/workflow/config.py's INSIGHTS_* env-var
        convention: the directory is read once at import time from
        INSIGHTS_PACKAGES_DIR, defaulting to <repo_root>/insight_packages."""
        import importlib

        monkeypatch.setenv("INSIGHTS_PACKAGES_DIR", str(tmp_path / "custom"))
        reloaded = importlib.reload(package_store)
        try:
            assert reloaded.INSIGHTS_PACKAGES_DIR == tmp_path / "custom"
        finally:
            monkeypatch.delenv("INSIGHTS_PACKAGES_DIR", raising=False)
            importlib.reload(package_store)
