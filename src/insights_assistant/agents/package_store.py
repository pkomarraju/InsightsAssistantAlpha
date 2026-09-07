"""Persists a manual, human-readable JSON snapshot of every synthesized
InsightPackage -- alongside the SourcePayloads it was built from and the
ReviewDecision it received -- to disk, one file per exact
(request_id, request_version, package_version).

This exists purely to let a developer review insight quality (input
evidence vs. output insights vs. what the Reviewer said about them) while
iterating on the Synthesizer/Reviewer prompts and logic. It is a one-way
debug/audit trail:
  - Never read back by the running application -- api/server.py's
    INSIGHTS_STORE (published, reviewable insights) and STORE (requests)
    remain the only things the API actually serves from.
  - Never allowed to affect request outcome: a write failure here is
    logged and swallowed, never raised, since this is a review aid, not a
    critical-path dependency.

Wired into agents/insight_workflow.py as an optional on_package_ready
callback -- the same injection pattern on_state_change already uses -- so
the workflow state machine itself stays pure and has no filesystem/JSON
dependency of its own.
"""

import json
import logging
import os
from pathlib import Path

from insights_assistant.contracts.workflow.packages import InsightPackage
from insights_assistant.contracts.workflow.research import SourcePayload
from insights_assistant.contracts.workflow.review import ReviewDecision

logger = logging.getLogger(__name__)

# repo root: src/insights_assistant/agents/package_store.py -> agents ->
# insights_assistant -> src -> repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PACKAGES_DIR = _REPO_ROOT / "insight_packages"

# Bare name (not bound as a default parameter value) so it stays
# monkeypatchable in tests, matching this repo's established convention
# (see contracts/workflow/config.py's module docstring).
INSIGHTS_PACKAGES_DIR = Path(os.environ.get("INSIGHTS_PACKAGES_DIR") or DEFAULT_PACKAGES_DIR)


def _snapshot_filename(package: InsightPackage) -> str:
    return f"rv{package.request_version}_pv{package.package_version}.json"


def save_package_snapshot(
    package: InsightPackage,
    source_payloads: list[SourcePayload],
    review_decision: ReviewDecision | None,
) -> Path | None:
    """Writes insight_packages/{request_id}/rv{request_version}_pv{package_version}.json.

    Contains the package's own fields (prompts, preferences, insights,
    unmet_requirements), the full source_payloads it was synthesized from
    (the research *input* -- every specialist's evidence and findings text,
    not just what survived into an insight), and the ReviewDecision this
    exact package received (None only if the caller has no decision yet,
    which the current workflow never does -- every package that reaches
    this function has already been reviewed).

    Returns the path written, or None if the write failed (logged, never
    raised -- see module docstring).
    """

    directory = INSIGHTS_PACKAGES_DIR / package.request_id
    path = directory / _snapshot_filename(package)

    snapshot = {
        "requestId": package.request_id,
        "requestVersion": package.request_version,
        "packageVersion": package.package_version,
        "createdAt": package.created_at.isoformat(),
        "originalUserPrompt": package.original_user_prompt,
        "effectiveResearchPrompt": package.effective_research_prompt,
        "preferences": package.preferences.model_dump(mode="json", by_alias=True),
        "sourcePayloads": [p.model_dump(mode="json", by_alias=True) for p in source_payloads],
        "insights": [i.model_dump(mode="json", by_alias=True) for i in package.insights],
        "unmetRequirements": [u.model_dump(mode="json", by_alias=True) for u in package.unmet_requirements],
        "reviewDecision": review_decision.model_dump(mode="json", by_alias=True) if review_decision else None,
    }

    try:
        directory.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(snapshot, indent=2))
    except OSError:
        logger.exception(
            "Failed to write package snapshot for request_id=%s request_version=%s package_version=%s",
            package.request_id, package.request_version, package.package_version,
        )
        return None

    logger.info("Saved package snapshot: %s", path)
    return path
