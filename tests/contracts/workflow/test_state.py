from datetime import timedelta

import pytest

from insights_assistant.contracts.api.enums import EvidenceSourceAgent
from insights_assistant.contracts.workflow.enums import SourcePayloadStatus, WorkflowStage
from insights_assistant.contracts.workflow.state import SourceErrorRecord, WorkflowInvariantError, WorkflowState


class TestWorkflowStateStart:
    def test_start_sets_researching_stage_and_defaults(self, now):
        state = WorkflowState.start("REQ_1", occurred_at=now)
        assert state.current_stage == WorkflowStage.RESEARCHING
        assert state.request_version == 1
        assert state.package_version == 1
        assert state.research_revision_count == 0
        assert state.synthesis_revision_count == 0
        assert len(state.audit_events) == 1


class TestWorkflowStateImmutability:
    def test_with_stage_returns_new_instance_leaves_original_unchanged(self, now):
        state = WorkflowState.start("REQ_1", occurred_at=now)
        moved = state.with_stage(WorkflowStage.SYNTHESIZING, message="synthesis started", occurred_at=now)

        assert moved is not state
        assert moved.current_stage == WorkflowStage.SYNTHESIZING
        assert state.current_stage == WorkflowStage.RESEARCHING

    def test_state_is_frozen(self, now):
        state = WorkflowState.start("REQ_1", occurred_at=now)
        with pytest.raises(Exception):
            state.current_stage = WorkflowStage.COMPLETED

    def test_with_stage_appends_not_replaces_audit_events(self, now):
        state = WorkflowState.start("REQ_1", occurred_at=now)
        moved = state.with_stage(WorkflowStage.SYNTHESIZING, message="m", occurred_at=now)
        assert len(moved.audit_events) == 2
        assert moved.audit_events[0] == state.audit_events[0]


class TestResearchRevision:
    def test_first_research_revision_increments_request_version(self, now):
        state = WorkflowState.start("REQ_1", occurred_at=now)
        revised = state.with_research_revision(occurred_at=now)
        assert revised.request_version == 2
        assert revised.research_revision_count == 1
        assert revised.current_stage == WorkflowStage.REVISING_RESEARCH

    def test_second_research_revision_raises(self, now):
        state = WorkflowState.start("REQ_1", occurred_at=now).with_research_revision(occurred_at=now)
        with pytest.raises(WorkflowInvariantError, match="research_revision_count"):
            state.with_research_revision(occurred_at=now)

    def test_research_revision_does_not_touch_package_version(self, now):
        state = WorkflowState.start("REQ_1", occurred_at=now)
        revised = state.with_research_revision(occurred_at=now)
        assert revised.package_version == state.package_version


class TestSynthesisRevision:
    def test_first_synthesis_revision_increments_package_version(self, now):
        state = WorkflowState.start("REQ_1", occurred_at=now)
        revised = state.with_synthesis_revision(occurred_at=now)
        assert revised.package_version == 2
        assert revised.synthesis_revision_count == 1
        assert revised.current_stage == WorkflowStage.REVISING_SYNTHESIS

    def test_second_synthesis_revision_succeeds_under_the_default_limit_of_two(self, now):
        state = WorkflowState.start("REQ_1", occurred_at=now).with_synthesis_revision(occurred_at=now)
        revised = state.with_synthesis_revision(occurred_at=now)
        assert revised.package_version == 3
        assert revised.synthesis_revision_count == 2

    def test_third_synthesis_revision_raises_under_the_default_limit_of_two(self, now):
        state = (
            WorkflowState.start("REQ_1", occurred_at=now)
            .with_synthesis_revision(occurred_at=now)
            .with_synthesis_revision(occurred_at=now)
        )
        with pytest.raises(WorkflowInvariantError, match="synthesis_revision_count is already at its maximum of 2"):
            state.with_synthesis_revision(occurred_at=now)

    def test_synthesis_revision_limit_is_read_from_configured_value(self, now, monkeypatch):
        """The check reads INSIGHTS_MAX_SYNTHESIS_REVISIONS as a bare
        module-level name at call time -- a monkeypatch takes effect
        immediately, without needing importlib.reload."""
        import insights_assistant.contracts.workflow.state as state_module

        monkeypatch.setattr(state_module, "INSIGHTS_MAX_SYNTHESIS_REVISIONS", 1)
        state = WorkflowState.start("REQ_1", occurred_at=now).with_synthesis_revision(occurred_at=now)
        with pytest.raises(WorkflowInvariantError, match="maximum of 1"):
            state.with_synthesis_revision(occurred_at=now)

    def test_synthesis_revision_does_not_touch_request_version(self, now):
        state = WorkflowState.start("REQ_1", occurred_at=now)
        revised = state.with_synthesis_revision(occurred_at=now)
        assert revised.request_version == state.request_version

    def test_research_and_synthesis_revisions_are_independent_caps(self, now):
        """Using one revision type doesn't consume the other's budget."""
        state = WorkflowState.start("REQ_1", occurred_at=now)
        state = state.with_research_revision(occurred_at=now)
        state = state.with_synthesis_revision(occurred_at=now)
        assert state.request_version == 2
        assert state.package_version == 2
        assert state.research_revision_count == 1
        assert state.synthesis_revision_count == 1


class TestSourceErrorsAndTerminalError:
    def test_with_source_error_appends_error_and_audit_event(self, now):
        state = WorkflowState.start("REQ_1", occurred_at=now)
        error = SourceErrorRecord(
            request_id="REQ_1", request_version=1, company_code="CLI_001",
            source_agent=EvidenceSourceAgent.EXTERNAL_DATA_AGENT,
            status=SourcePayloadStatus.TIMED_OUT, error="EDGAR did not respond", occurred_at=now,
        )
        updated = state.with_source_error(error, occurred_at=now)
        assert len(updated.source_errors) == 1
        assert len(updated.audit_events) == 2

    def test_with_terminal_error_sets_failed_stage(self, now):
        state = WorkflowState.start("REQ_1", occurred_at=now)
        failed = state.with_terminal_error("revision limits exhausted", occurred_at=now)
        assert failed.current_stage == WorkflowStage.FAILED
        assert failed.terminal_error == "revision limits exhausted"
