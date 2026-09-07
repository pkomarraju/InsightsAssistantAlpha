import importlib

import pytest

from insights_assistant.contracts.workflow import config


def test_default_execution_timeout_is_one_hour():
    """Batch-processing semantics: specialist agents may legitimately take
    several minutes, so the per-specialist safety timeout is a full hour by
    default -- not a number tuned for a fast/interactive turnaround -- and
    only an explicit env override should ever move it."""
    assert config.DEFAULT_SOURCE_EXECUTION_TIMEOUT_SECONDS == 3600.0
    assert config.INSIGHTS_SOURCE_EXECUTION_TIMEOUT_SECONDS > 0


def test_default_overhead_is_positive():
    assert config.DEFAULT_RESEARCH_WORKFLOW_TIMEOUT_OVERHEAD_SECONDS > 0
    assert config.INSIGHTS_RESEARCH_WORKFLOW_TIMEOUT_OVERHEAD_SECONDS > 0


def test_workflow_timeout_and_legacy_join_timeout_are_unset_by_default(monkeypatch):
    """Both are optional overrides -- their absence is meaningful (nothing
    to validate against, or no legacy behavior to preserve), unlike the
    execution timeout and overhead, which always have a concrete default.
    Explicitly clears both env vars first: some other test module's import
    of agents/orchestrator.py may already have loaded .env into os.environ
    by the time this runs (pytest collects/imports every test module before
    running any test function), so the ambient environment can't be assumed
    clean -- the other tests below don't need this because they always set
    an explicit value right before reloading."""
    monkeypatch.delenv("INSIGHTS_RESEARCH_WORKFLOW_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("INSIGHTS_SOURCE_JOIN_TIMEOUT_SECONDS", raising=False)
    reloaded = importlib.reload(config)
    try:
        assert reloaded.INSIGHTS_RESEARCH_WORKFLOW_TIMEOUT_SECONDS is None
        assert reloaded.INSIGHTS_SOURCE_JOIN_TIMEOUT_SECONDS is None
    finally:
        importlib.reload(config)


def test_execution_timeout_env_override_is_respected(monkeypatch):
    monkeypatch.setenv("INSIGHTS_SOURCE_EXECUTION_TIMEOUT_SECONDS", "45")
    reloaded = importlib.reload(config)
    try:
        assert reloaded.INSIGHTS_SOURCE_EXECUTION_TIMEOUT_SECONDS == 45.0
    finally:
        monkeypatch.delenv("INSIGHTS_SOURCE_EXECUTION_TIMEOUT_SECONDS", raising=False)
        importlib.reload(config)


def test_workflow_timeout_env_override_is_respected(monkeypatch):
    monkeypatch.setenv("INSIGHTS_RESEARCH_WORKFLOW_TIMEOUT_SECONDS", "600")
    reloaded = importlib.reload(config)
    try:
        assert reloaded.INSIGHTS_RESEARCH_WORKFLOW_TIMEOUT_SECONDS == 600.0
    finally:
        monkeypatch.delenv("INSIGHTS_RESEARCH_WORKFLOW_TIMEOUT_SECONDS", raising=False)
        importlib.reload(config)


def test_legacy_join_timeout_env_var_still_works(monkeypatch):
    """Backward compatibility: the retired single-timeout knob still sets a
    value (used by agents.research_execution.compute_research_workflow_timeout_seconds
    as an override of everything else) rather than being silently ignored."""
    monkeypatch.setenv("INSIGHTS_SOURCE_JOIN_TIMEOUT_SECONDS", "45")
    reloaded = importlib.reload(config)
    try:
        assert reloaded.INSIGHTS_SOURCE_JOIN_TIMEOUT_SECONDS == 45.0
    finally:
        monkeypatch.delenv("INSIGHTS_SOURCE_JOIN_TIMEOUT_SECONDS", raising=False)
        importlib.reload(config)


@pytest.mark.parametrize("bad_value", ["0", "-10", "-0.5"])
def test_non_positive_execution_timeout_raises_at_import(monkeypatch, bad_value):
    monkeypatch.setenv("INSIGHTS_SOURCE_EXECUTION_TIMEOUT_SECONDS", bad_value)
    try:
        with pytest.raises(ValueError, match="must be positive"):
            importlib.reload(config)
    finally:
        monkeypatch.delenv("INSIGHTS_SOURCE_EXECUTION_TIMEOUT_SECONDS", raising=False)
        importlib.reload(config)


@pytest.mark.parametrize("bad_value", ["0", "-10", "-0.5"])
def test_non_positive_workflow_timeout_raises_at_import(monkeypatch, bad_value):
    monkeypatch.setenv("INSIGHTS_RESEARCH_WORKFLOW_TIMEOUT_SECONDS", bad_value)
    try:
        with pytest.raises(ValueError, match="must be positive"):
            importlib.reload(config)
    finally:
        monkeypatch.delenv("INSIGHTS_RESEARCH_WORKFLOW_TIMEOUT_SECONDS", raising=False)
        importlib.reload(config)


def test_domain_id_constants_are_disjoint():
    assert config.RELATIONSHIP_INTERACTIONS_DOMAIN_ID not in config.STRUCTURED_DATA_DOMAIN_IDS


def test_default_max_synthesis_revisions_is_two(monkeypatch):
    monkeypatch.delenv("INSIGHTS_MAX_SYNTHESIS_REVISIONS", raising=False)
    reloaded = importlib.reload(config)
    try:
        assert config.DEFAULT_MAX_SYNTHESIS_REVISIONS == 2
        assert reloaded.INSIGHTS_MAX_SYNTHESIS_REVISIONS == 2
    finally:
        importlib.reload(config)


def test_max_synthesis_revisions_env_override_is_respected(monkeypatch):
    monkeypatch.setenv("INSIGHTS_MAX_SYNTHESIS_REVISIONS", "3")
    reloaded = importlib.reload(config)
    try:
        assert reloaded.INSIGHTS_MAX_SYNTHESIS_REVISIONS == 3
    finally:
        monkeypatch.delenv("INSIGHTS_MAX_SYNTHESIS_REVISIONS", raising=False)
        importlib.reload(config)


@pytest.mark.parametrize("bad_value", ["0", "-1", "-10"])
def test_non_positive_max_synthesis_revisions_raises_at_import(monkeypatch, bad_value):
    monkeypatch.setenv("INSIGHTS_MAX_SYNTHESIS_REVISIONS", bad_value)
    try:
        with pytest.raises(ValueError, match="must be positive"):
            importlib.reload(config)
    finally:
        monkeypatch.delenv("INSIGHTS_MAX_SYNTHESIS_REVISIONS", raising=False)
        importlib.reload(config)


def test_non_numeric_max_synthesis_revisions_fails_clearly_at_import(monkeypatch):
    """Consistent with every other INSIGHTS_* setting: a non-numeric value
    isn't caught and rewrapped -- int()'s own ValueError propagates as-is."""
    monkeypatch.setenv("INSIGHTS_MAX_SYNTHESIS_REVISIONS", "not-a-number")
    try:
        with pytest.raises(ValueError, match="invalid literal for int"):
            importlib.reload(config)
    finally:
        monkeypatch.delenv("INSIGHTS_MAX_SYNTHESIS_REVISIONS", raising=False)
        importlib.reload(config)


def test_default_synthesis_validation_retry_limit_is_two(monkeypatch):
    monkeypatch.delenv("INSIGHTS_SYNTHESIS_VALIDATION_RETRY_LIMIT", raising=False)
    reloaded = importlib.reload(config)
    try:
        assert config.DEFAULT_SYNTHESIS_VALIDATION_RETRY_LIMIT == 2
        assert reloaded.INSIGHTS_SYNTHESIS_VALIDATION_RETRY_LIMIT == 2
    finally:
        importlib.reload(config)


def test_synthesis_validation_retry_limit_env_override_is_respected(monkeypatch):
    monkeypatch.setenv("INSIGHTS_SYNTHESIS_VALIDATION_RETRY_LIMIT", "1")
    reloaded = importlib.reload(config)
    try:
        assert reloaded.INSIGHTS_SYNTHESIS_VALIDATION_RETRY_LIMIT == 1
    finally:
        monkeypatch.delenv("INSIGHTS_SYNTHESIS_VALIDATION_RETRY_LIMIT", raising=False)
        importlib.reload(config)


@pytest.mark.parametrize("bad_value", ["0", "-1"])
def test_non_positive_synthesis_validation_retry_limit_raises_at_import(monkeypatch, bad_value):
    monkeypatch.setenv("INSIGHTS_SYNTHESIS_VALIDATION_RETRY_LIMIT", bad_value)
    try:
        with pytest.raises(ValueError, match="must be positive"):
            importlib.reload(config)
    finally:
        monkeypatch.delenv("INSIGHTS_SYNTHESIS_VALIDATION_RETRY_LIMIT", raising=False)
        importlib.reload(config)
