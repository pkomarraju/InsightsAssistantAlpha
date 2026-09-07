"""Cross-object invariants that reason over a list of SourcePayload plus a
ResearchManifest together -- these can't live as a validator on any single
model, since they compare records against each other.
"""

from insights_assistant.contracts.api.enums import EvidenceSourceAgent
from insights_assistant.contracts.workflow.enums import SourcePayloadStatus
from insights_assistant.contracts.workflow.research import PayloadKey, ResearchManifest, SourcePayload


class WorkflowInvariantError(ValueError):
    """Raised by the functions in this module when a set of payloads/a
    manifest violates one of the task's stated invariants."""


def validate_unique_payload_keys(payloads: list[SourcePayload]) -> None:
    """At most one payload per request/version/company/source key."""

    seen: set[tuple[str, int, str, str]] = set()
    for payload in payloads:
        identity = (payload.request_id, payload.request_version, payload.company_code, payload.source_agent.value)
        if identity in seen:
            raise WorkflowInvariantError(
                f"duplicate SourcePayload for request_id={payload.request_id!r} "
                f"request_version={payload.request_version} company_code={payload.company_code!r} "
                f"source_agent={payload.source_agent.value!r}"
            )
        seen.add(identity)


def validate_single_request_version(payloads: list[SourcePayload], request_id: str, request_version: int) -> None:
    """Never mix payloads from different request versions."""

    for payload in payloads:
        if payload.request_id != request_id:
            raise WorkflowInvariantError(
                f"payload request_id={payload.request_id!r} does not match expected request_id={request_id!r}"
            )
        if payload.request_version != request_version:
            raise WorkflowInvariantError(
                f"payload for company_code={payload.company_code!r} source_agent={payload.source_agent.value!r} "
                f"has request_version={payload.request_version}, expected {request_version} -- "
                "payloads from different request versions must never be mixed"
            )


def is_manifest_ready(manifest: ResearchManifest, payloads: list[SourcePayload]) -> bool:
    """True only when every expected payload key has a matching, completed
    payload for this exact request_id/request_version."""

    validate_unique_payload_keys(payloads)
    validate_single_request_version(payloads, manifest.request_id, manifest.request_version)

    completed_keys: set[tuple[str, EvidenceSourceAgent]] = {
        payload.key.as_tuple()
        for payload in payloads
        if payload.status == SourcePayloadStatus.COMPLETED
    }
    expected_keys: set[tuple[str, EvidenceSourceAgent]] = {key.as_tuple() for key in manifest.expected_payload_keys}
    return expected_keys.issubset(completed_keys)


def ensure_ready_for_synthesis(manifest: ResearchManifest, payloads: list[SourcePayload]) -> None:
    """No synthesis until every expected payload for the exact request_id and
    request_version is completed successfully. Raises WorkflowInvariantError
    naming exactly which expected keys are missing or did not complete.
    """

    validate_unique_payload_keys(payloads)
    validate_single_request_version(payloads, manifest.request_id, manifest.request_version)

    by_key: dict[tuple[str, EvidenceSourceAgent], SourcePayload] = {
        payload.key.as_tuple(): payload for payload in payloads
    }

    missing: list[PayloadKey] = []
    not_completed: list[SourcePayload] = []
    for expected in manifest.expected_payload_keys:
        payload = by_key.get(expected.as_tuple())
        if payload is None:
            missing.append(expected)
        elif payload.status != SourcePayloadStatus.COMPLETED:
            not_completed.append(payload)

    if missing or not_completed:
        problems = [f"{key.company_code}/{key.source_agent.value}: missing" for key in missing]
        problems += [
            f"{payload.company_code}/{payload.source_agent.value}: {payload.status.value}"
            for payload in not_completed
        ]
        raise WorkflowInvariantError(
            f"not ready for synthesis (request_id={manifest.request_id!r} "
            f"request_version={manifest.request_version}): " + "; ".join(problems)
        )
