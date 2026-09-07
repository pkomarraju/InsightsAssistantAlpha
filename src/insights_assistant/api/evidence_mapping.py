"""Evidence-code taxonomy shared by insight synthesis and assistant chat
citations. Mirrors docs/api/MAPPING.md's "Evidence code -> source mapping"
table -- kept in one place so both call sites classify a code the same way.

Also owns the deterministic evidence-semantics classifier
(classify_evidence_semantics): which risk domain(s), claim families, and
monetary-metric kind one evidence item's own reported text (label + detail,
as the specialist reported it from real tool output) is capable of
supporting. This is what fixes the REQ_1005 failure at its root -- a
worsening relationship_risk_score used to be treated as credit-risk evidence
purely because its evidence_code started with "RISK_"; that prefix now only
narrows which *kind* of structured record produced the item (see PREFIX_MAP),
never what risk domain or claim it substantively supports. All of it is
pattern-based over the evidence item's own text, never over an insight's
generated finding/why_it_matters prose -- evidence controls the inference,
not the reverse (the same principle agents/synthesizer.py's contradiction
check already applies).
"""

import re
from typing import NamedTuple

from insights_assistant.contracts.api.enums import ClaimType, MonetaryMetricType, RiskType
from insights_assistant.contracts.api.evidence import EvidenceItem

SourceAgent = str
SourceType = str

# prefix -> (sourceAgent, sourceType, generic label)
PREFIX_MAP: dict[str, tuple[SourceAgent, SourceType, str]] = {
    "REL_": ("internal_data_agent", "internal", "Relationship snapshot"),
    "RELM_": ("internal_data_agent", "internal", "Relationship metric history"),
    "PROD_": ("internal_data_agent", "internal", "Product usage"),
    "OPP_": ("internal_data_agent", "internal", "Opportunity pipeline"),
    "RISK_": ("internal_data_agent", "internal", "Risk assessment"),
    "INT_": ("internal_data_agent", "internal", "Client interaction"),
    "NOTE_": ("internal_data_agent", "internal", "Internal note"),
    "RMN_": ("relationship_notes_agent", "internal", "Relationship manager note"),
    # external_data_agent (agents/orchestrator.py's SPECIALIST_PROMPTS):
    # unlike the internal prefixes above, FMP/Alpha Vantage/FRED don't hand
    # back a pre-existing evidence_code of their own -- the specialist
    # constructs one itself (FMP_<TICKER>_<METRIC>_<PERIOD>,
    # AV_<TICKER>_<DATASET>[_<DATE>], FRED_<SERIES_ID>_<DATE>), so these
    # prefixes exist purely so that self-constructed code still classifies
    # the same deterministic way every internal one does.
    "FMP_": ("external_data_agent", "external", "Financial Modeling Prep data"),
    "AV_": ("external_data_agent", "external", "Alpha Vantage market data"),
    "FRED_": ("external_data_agent", "external", "FRED macro/benchmark rate"),
    # mcp_servers/internal_data_server.py's get_company_research_context,
    # backed by sql/new_internal_data_tables.sql's bank_credit_exposures/
    # crm_deal_pipeline/internal_risk_flags -- application-generated,
    # ticker-based codes (EXP_<TICKER>_<id>, not a bare digit run like the
    # legacy prefixes above), same reasoning as FMP/AV/FRED's own entries.
    "EXP_": ("internal_data_agent", "internal", "Credit facility"),
    "DEAL_": ("internal_data_agent", "internal", "CRM deal pipeline"),
    "RISKFLAG_": ("internal_data_agent", "internal", "Internal risk flag"),
}

# internal_data_agent's two generations of evidence prefix -- the original
# company_master/relationship_snapshot/products/opportunities/
# risk_assessment/client_interactions/internal_notes tables versus the new
# target_companies/bank_credit_exposures/crm_deal_pipeline/
# internal_risk_flags ones (get_company_research_context). Used by
# agents/research_execution.py to deterministically drop legacy evidence a
# task reports when its request selected the new schema exclusively -- see
# contracts.workflow.config.is_new_schema_only_selection.
LEGACY_INTERNAL_DATA_AGENT_PREFIXES = frozenset({"REL_", "RELM_", "PROD_", "OPP_", "RISK_", "INT_", "NOTE_"})
NEW_SCHEMA_INTERNAL_DATA_AGENT_PREFIXES = frozenset({"EXP_", "DEAL_", "RISKFLAG_"})

_CODE_RE = re.compile(
    r"\b(?:REL|RELM|PROD|OPP|RISK|INT|NOTE|RMN)_[0-9]{3,}\b"
)
# The external prefixes, and the new ticker-based internal ones just above,
# are followed by a ticker/series id, not a bare digit run, so they need
# their own, more permissive pattern.
_EXTERNAL_CODE_RE = re.compile(r"\b(?:FMP|AV|FRED|EXP|DEAL|RISKFLAG)_[A-Z0-9][A-Z0-9_-]*\b")


def classify(code: str) -> tuple[SourceAgent, SourceType] | None:
    """Returns (sourceAgent, sourceType) for a known evidence code, or None
    if the code doesn't match any known prefix -- callers should drop
    evidence they can't classify rather than guess.
    """
    for prefix, (agent, source_type, _label) in PREFIX_MAP.items():
        if code.startswith(prefix):
            return agent, source_type
    return None


def label_for(code: str) -> str:
    for prefix, (_agent, _source_type, label) in PREFIX_MAP.items():
        if code.startswith(prefix):
            return label
    return code


def extract_codes(text: str) -> list[str]:
    """Best-effort scan of free text for known evidence-code patterns. Used
    by the assistant chat endpoint, where a second LLM call per turn would
    be too slow -- regex extraction is a cheaper approximation of the same
    citations the orchestrator already put in its answer.
    """
    codes = list(dict.fromkeys(_CODE_RE.findall(text)))
    for match in _EXTERNAL_CODE_RE.findall(text):
        if match not in codes:
            codes.append(match)
    return codes


# --- Evidence semantics: risk type / claim / monetary-metric classification ---
#
# Deliberately narrow, specific vocabulary per pattern -- a generic word like
# "risk", "elevated", or "worsening" on its own says nothing about *which*
# risk domain is meant, which is exactly how the REQ_1005 bug happened
# (a worsening *relationship*-risk score read as *credit*-risk deterioration).
# Every pattern below requires the domain-specific noun/phrase, not just a
# direction word.

_CREDIT_QUALITY_PATTERN = re.compile(
    r"\b(rating downgrade\w*|downgrad\w* (?:the )?(?:credit )?rating|"
    r"covenant (?:breach|pressure|violation)\w*|delinquen\w*|\bdefault\w*|"
    r"probability of default|criticized (?:exposure|loan|asset)\w*|"
    r"classified (?:exposure|loan|asset)\w*|repayment capacity|liquidity stress|"
    r"credit rating (?:downgrade|deterioration)|"
    r"credit quality (?:deterioration|worsening|declin\w*))\b",
    re.IGNORECASE,
)

_RELATIONSHIP_RISK_PATTERN = re.compile(
    r"\brelationship[\s-]?(?:risk|status|strength)\b|"
    r"\b(?:relationship )?at[\s-]?risk (?:flag|designation)\b|"
    r"\brelationship (?:is |remains? )?deteriorat\w*|"
    r"\brelationship revenue (?:declin\w*|down|eroding)\b",
    re.IGNORECASE,
)

_CONCENTRATION_RISK_PATTERN = re.compile(r"\bconcentration risk\b", re.IGNORECASE)
_OPERATIONAL_RISK_PATTERN = re.compile(r"\boperational risk\b", re.IGNORECASE)

_WORSENING_DIRECTION_PATTERN = re.compile(
    r"\b(wors(?:e|en\w*)|deteriorat\w*|declin\w*|rising risk|increasing risk|"
    r"elevated|accelerating)\b",
    re.IGNORECASE,
)

_COMPETITOR_SHARE_LOSS_PATTERN = re.compile(
    r"\blost (?:the )?(?:mandate|deal|opportunity|bid)\b|\blost\b.{0,40}\bto\b|"
    r"\bcompetitor\w*\b|\bleading\b.{0,25}\bconversations\b|\bshare loss\b|"
    r"\blosing (?:market )?share\b",
    re.IGNORECASE,
)

_REVENUE_DECLINE_PATTERN = re.compile(
    r"\brevenue (?:declin\w*|down|decreas\w*|eroding)\b|\bdeclining\b.{0,20}\brevenue\b",
    re.IGNORECASE,
)

_CROSS_SELL_OPPORTUNITY_PATTERN = re.compile(
    r"\bcross[\s-]?sell\b|\bexpansion opportunity\b|\bwhitespace\b|"
    r"\badditional product\b|\bnew mandate opportunity\b",
    re.IGNORECASE,
)

_NO_MATERIAL_IMPACT_PATTERN = re.compile(
    r"\bno (?:material|current) (?:impact|financial impact)\b|"
    r"\bnot (?:currently )?at risk\b|\bremains? (?:stable|strong|healthy)\b",
    re.IGNORECASE,
)

_CREDIT_EXPOSURE_METRIC_PATTERN = re.compile(r"\bcredit exposure\b", re.IGNORECASE)
_ESTIMATED_LOSS_METRIC_PATTERN = re.compile(r"\b(?:estimated|expected) loss\b", re.IGNORECASE)
_REVENUE_METRIC_PATTERN = re.compile(r"\b(?:annual|relationship|product) revenue\b", re.IGNORECASE)
_OPPORTUNITY_VALUE_METRIC_PATTERN = re.compile(
    r"\b(?:opportunity|mandate|deal) value\b|\bmandate\b.{0,20}\$", re.IGNORECASE
)
_DOLLAR_FIGURE_PATTERN = re.compile(r"\$\s?[\d,]+(?:\.\d+)?")


class EvidenceSemantics(NamedTuple):
    risk_types: tuple[RiskType, ...]
    supported_claims: tuple[ClaimType, ...]
    metric_type: MonetaryMetricType | None


def classify_evidence_semantics(evidence_code: str, label: str, detail: str) -> EvidenceSemantics:
    """Deterministic, pattern-based semantic tagging of one evidence item's
    OWN text (label + detail). Populates EvidenceItem.risk_types/
    supported_claims/metric_type when an EvidenceItem is built (see
    agents/research_execution.py::_build_evidence) -- never re-derived from
    an insight's own generated prose.

    For RISK_048 specifically (Exxon Mobil's risk_assessment row, whose
    explanatory_comment is "Relationship risk trending sharply worse; a
    second lost mandate to the same named competitor within two quarters
    signals accelerating share loss..."), this returns
    risk_types=(RELATIONSHIP_RISK,),
    supported_claims=(COMPETITOR_SHARE_LOSS, RELATIONSHIP_RISK_WORSENING) --
    and never CREDIT_RISK or CREDIT_QUALITY_DETERIORATING, since the text
    contains no direct credit-quality vocabulary at all.
    """

    text = f"{label} {detail}"
    worsening = bool(_WORSENING_DIRECTION_PATTERN.search(text))

    risk_types: set[RiskType] = set()
    claims: set[ClaimType] = set()

    if _CREDIT_QUALITY_PATTERN.search(text):
        # This vocabulary is itself a statement of deterioration -- a rating
        # downgrade or covenant breach is never reported as "good news".
        risk_types.add(RiskType.CREDIT_RISK)
        claims.add(ClaimType.CREDIT_QUALITY_DETERIORATING)

    if _RELATIONSHIP_RISK_PATTERN.search(text):
        risk_types.add(RiskType.RELATIONSHIP_RISK)
        if worsening:
            claims.add(ClaimType.RELATIONSHIP_RISK_WORSENING)

    if _CONCENTRATION_RISK_PATTERN.search(text):
        risk_types.add(RiskType.CONCENTRATION_RISK)

    if _OPERATIONAL_RISK_PATTERN.search(text):
        risk_types.add(RiskType.OPERATIONAL_RISK)

    if _COMPETITOR_SHARE_LOSS_PATTERN.search(text):
        claims.add(ClaimType.COMPETITOR_SHARE_LOSS)

    if _REVENUE_DECLINE_PATTERN.search(text):
        claims.add(ClaimType.REVENUE_DECLINE)

    if _CROSS_SELL_OPPORTUNITY_PATTERN.search(text):
        claims.add(ClaimType.PRODUCT_OR_CROSS_SELL_OPPORTUNITY)

    # The four new-schema demo categories (contracts.api.enums.InsightCategory)
    # gate on evidence *source*, not text pattern -- each prefix's own tool
    # (mcp_servers/internal_data_server.py, agents/external_adapters.py)
    # already only ever reports the kind of fact its category needs, so
    # requiring a prefix is enough; no brittle new regex is needed on top.
    # A facility (EXP_) or FRED rate never implies financial_performance --
    # that's specifically about the company's own results (FMP/AV) -- and
    # neither implies risk_coverage_attention or deal_fee_opportunity, which
    # each require their own distinct evidence (an internal risk flag or an
    # actual CRM pipeline record, never invented from unrelated evidence).
    if evidence_code.startswith("EXP_") or evidence_code.startswith("FRED_"):
        claims.add(ClaimType.FINANCING_LIQUIDITY_SIGNAL)
    if evidence_code.startswith("FMP_") or evidence_code.startswith("AV_"):
        claims.add(ClaimType.FINANCING_LIQUIDITY_SIGNAL)
        claims.add(ClaimType.FINANCIAL_PERFORMANCE_SIGNAL)
    if evidence_code.startswith("DEAL_"):
        claims.add(ClaimType.DEAL_FEE_OPPORTUNITY)
    # RISKFLAG_ is the dedicated internal_risk_flags table's own prefix --
    # always a genuine flag, so it is tagged unconditionally. The older,
    # general-purpose RISK_ prefix (quarterly risk_assessment) deliberately
    # is NOT included here: its relationship-risk/concentration-risk content
    # already has its own well-defined claims above (relationship_risk_
    # worsening, competitor_share_loss, credit_quality_deteriorating), and
    # its dollar-valued column is a bare credit-exposure figure with no
    # risk-flag content at all -- neither is "an internal risk flag" in the
    # sense risk_coverage_attention requires (see agents/synthesizer.py's
    # SYNTHESIS_SYSTEM_PROMPT rule 8 and tests/api/test_evidence_mapping.py's
    # RISK_048 golden case, which pins RISK_ evidence to relationship-risk
    # claims only).
    if evidence_code.startswith("RISKFLAG_"):
        claims.add(ClaimType.RISK_COVERAGE_ATTENTION)

    if not risk_types and not claims and _NO_MATERIAL_IMPACT_PATTERN.search(text):
        claims.add(ClaimType.NO_MATERIAL_IMPACT)

    metric_type: MonetaryMetricType | None = None
    if _CREDIT_EXPOSURE_METRIC_PATTERN.search(text):
        metric_type = MonetaryMetricType.CREDIT_EXPOSURE
    elif _ESTIMATED_LOSS_METRIC_PATTERN.search(text):
        metric_type = MonetaryMetricType.ESTIMATED_LOSS
    elif _OPPORTUNITY_VALUE_METRIC_PATTERN.search(text) or evidence_code.startswith(("OPP_", "DEAL_")):
        # DEAL_'s potential_fee_usd (crm_deal_pipeline) is an opportunity
        # value, exactly like the legacy OPP_ opportunity_value column --
        # never exposure, and never business impact on its own (Goal D).
        metric_type = MonetaryMetricType.OPPORTUNITY_VALUE
    elif _REVENUE_METRIC_PATTERN.search(text):
        metric_type = MonetaryMetricType.REVENUE
    elif evidence_code.startswith("EXP_"):
        # bank_credit_exposures' committed/drawn amounts are exposure --
        # never estimated impact and never opportunity value on their own.
        metric_type = MonetaryMetricType.CREDIT_EXPOSURE
    elif evidence_code.startswith("RISK_") and _DOLLAR_FIGURE_PATTERN.search(text):
        # risk_assessment's only dollar-valued column is credit_exposure
        # (sql/internal_tables.sql) -- a known-schema fallback, not a guess,
        # for when the specialist reports the figure without the words
        # "credit exposure" attached.
        metric_type = MonetaryMetricType.CREDIT_EXPOSURE

    return EvidenceSemantics(
        risk_types=tuple(sorted(risk_types, key=lambda r: r.value)),
        supported_claims=tuple(sorted(claims, key=lambda c: c.value)),
        metric_type=metric_type,
    )


# Applied only to the *cited evidence's* own label/detail text (real,
# grounded source data), never to an insight's own generated finding/
# why_it_matters -- evidence controls the inference, not the reverse.
_STABLE_RISK_PATTERN = re.compile(
    r"\b(stable|improving|improved|controlled|mitigated|well[- ]managed|low[- ]risk|"
    r"effective (?:credit[- ])?risk management|strong (?:credit|financial) position|"
    r"sufficient (?:capital|liquidity)|adequate (?:capital|liquidity))\b",
    re.IGNORECASE,
)
_ELEVATED_RISK_PATTERN = re.compile(
    r"\b(elevated|worsening|deteriorat\w*|downgrade\w*|delinquenc\w*|default|"
    r"covenant (?:breach|pressure|violation)|criticized|classified|liquidity stress|"
    r"distress\w*|high[- ]risk|increasing risk|rising risk)\b",
    re.IGNORECASE,
)

# Evidence-based confidence ceilings (requirement 6), shared by
# agents/synthesizer.py (applied to a freshly synthesized draft) and
# agents/reviewer.py (recomputed as a deterministic defense-in-depth check
# on an already-assembled RankedInsight) so both agree on exactly the same
# rule.
SINGLE_EVIDENCE_CONFIDENCE_CAP = 70
SINGLE_SOURCE_TYPE_CONFIDENCE_CAP = 80
MULTI_SOURCE_TYPE_CONFIDENCE_CAP = 90
MIXED_EVIDENCE_CONFIDENCE_CAP = 65


def evidence_is_mixed(items: list[EvidenceItem]) -> bool:
    """True when the cited evidence itself contains both a stable/controlled
    signal and an elevated/worsening signal -- genuinely conflicting source
    data. Text-pattern-based over each item's own label/detail, never over
    an insight's generated prose."""

    def _matches(pattern: re.Pattern) -> bool:
        return any(pattern.search(f"{item.label} {item.detail}") for item in items)

    return _matches(_STABLE_RISK_PATTERN) and _matches(_ELEVATED_RISK_PATTERN)


def compute_confidence_cap(items: list[EvidenceItem], *, mixed: bool | None = None) -> int:
    """Deterministic confidence ceiling from evidence breadth and
    independence: one evidence item caps at 70; multiple items citing only
    one source *type* (internal vs. external -- internal_data_agent and
    relationship_notes_agent both read the bank's own systems, so neither
    alone counts as independent of the other) cap at 80; at least two
    independent source types allow up to 90; genuinely mixed/contradictory
    cited evidence caps at 65 regardless of breadth. `mixed` is computed via
    evidence_is_mixed(items) when not given explicitly."""

    if mixed is None:
        mixed = evidence_is_mixed(items)

    unique = list({item.evidence_code: item for item in items}.values())
    source_types = {item.source_type for item in unique}

    if len(unique) <= 1:
        cap = SINGLE_EVIDENCE_CONFIDENCE_CAP
    elif len(source_types) >= 2:
        cap = MULTI_SOURCE_TYPE_CONFIDENCE_CAP
    else:
        cap = SINGLE_SOURCE_TYPE_CONFIDENCE_CAP

    if mixed:
        cap = min(cap, MIXED_EVIDENCE_CONFIDENCE_CAP)
    return cap


def has_direct_credit_quality_evidence(items: list[EvidenceItem]) -> bool:
    """True only when at least one evidence item's own classified semantics
    support ClaimType.CREDIT_QUALITY_DETERIORATING -- a rating downgrade,
    covenant pressure/breach, delinquency, rising probability of default,
    criticized/classified exposure, reduced repayment capacity, liquidity
    stress, or an explicit credit-quality assessment showing deterioration.
    Replaces the old prefix-only is_direct_credit_risk_evidence: an
    evidence_code starting with "RISK_" is no longer, by itself, sufficient
    -- that prefix also covers relationship-risk and concentration-risk
    assessments that carry no credit-quality signal at all.
    """

    return any(ClaimType.CREDIT_QUALITY_DETERIORATING in item.supported_claims for item in items)
