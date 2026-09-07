import asyncio
import logging

# Must run before `from insights_assistant.llm import chat_model` below:
# llm.py reads INSIGHTS_MODEL/INSIGHTS_LLM_MIN_INTERVAL_SECONDS/etc. into
# module-level constants at import time, not lazily -- see the matching
# comment in api/server.py. When this module is imported first (e.g. `python
# -m insights_assistant.agents.orchestrator`, or transitively from
# research_execution.py before api/server.py's own load_dotenv() runs), a
# load_dotenv() call placed after that import is too late to have any effect.
from dotenv import load_dotenv

load_dotenv()

from langchain.agents import create_agent
from langgraph_supervisor import create_supervisor
from pydantic import BaseModel, Field

from insights_assistant.agents.external_adapters import build_external_adapter_tools
from insights_assistant.contracts.api.enums import EvidenceSourceAgent
from insights_assistant.contracts.workflow.external_research import ProviderStatusReport
from insights_assistant.llm import chat_model
from insights_assistant.mcp_client import load_tools

logger = logging.getLogger(__name__)


class SpecialistEvidenceItem(BaseModel):
    evidence_code: str = Field(
        description="The exact evidence_code/citation from a tool result (e.g. RISK_048, RMN_007, "
        "a filing accession number) -- copied verbatim, never invented."
    )
    date: str = Field(
        description="The exact date associated with that tool result (as_of_date, note_date, "
        "observation_month, filing date, etc.) in ISO YYYY-MM-DD format. Use the real date from "
        "the tool output, never today's date or a placeholder."
    )
    label: str = Field(description="Short label for what kind of evidence this is.")
    detail: str = Field(description="One or two sentences of concise supporting detail from the tool result.")


class SpecialistFindings(BaseModel):
    summary: str = Field(description="Concise factual summary of what was found for this company and source.")
    evidence: list[SpecialistEvidenceItem] = Field(default_factory=list)
    provider_statuses: list[ProviderStatusReport] = Field(
        default_factory=list,
        description="external_data_agent only: one entry per curated adapter actually called (see "
        "agents/external_adapters.py), self-reported from that adapter's own ProviderCallResult JSON "
        "(provider, status, message) -- never omitted for a non-completed status. Empty for "
        "internal_data_agent/relationship_notes_agent, which have no per-provider concept.",
    )

RELATIONSHIP_NOTES_AGENT_PROMPT = """You retrieve and analyze unstructured relationship-manager notes.

Rules:
0. search_relationship_notes' company_codes filter requires the exact internal code (format CLI_xxx),
   never a ticker or company name -- it does no fuzzy matching, so a wrong guess silently returns zero
   results instead of erroring. Use the company_code verbatim exactly as given in the request. If the
   request only names a company by ticker or name without giving you its CLI_xxx code, omit company_codes
   entirely and rely on the semantic query plus company_name in each result to confirm the match -- never
   guess a code.
1. Use the date range supplied by the insight_research request.
2. If the request says "recent" without a date range, interpret it as the last
   90 days relative to as_of_date.
3. When asked for all matching companies, retrieve and assess every company
   represented in the date range. Do not rely on a small semantic top_k.
4. A company is flagged at risk by the relationship manager only when a note
   explicitly describes the overall client relationship as currently at risk,
   critical, likely to churn, or uses unmistakably equivalent language.
5. Do not confuse relationship risk with project, implementation, opportunity,
   schedule, operational, or milestone risk.
6. Negative sentiment, declining revenue, competitor activity, and service
   complaints may explain a risk flag but do not independently establish an
   explicit RM flag.
7. When notes conflict, use the newest applicable note.
8. A newer resolution or explicit "not at risk" statement overrides an older
   concern.
9. Cite note_id and note_date for every conclusion.
10. Never invent evidence, companies, dates, or identifiers.

Return:
- company_code
- company_name
- relationship_manager
- current assessment
- note_id
- note_date
- concise supporting excerpt"""

SUPERVISOR_PROMPT = """You orchestrate between three specialists:

- external_data_agent: Public-company market data through five curated tools -- financial health and
  valuation (FMP), company profile/price/earnings (Alpha Vantage), and benchmark/macro rates (FRED).
- internal_data_agent: Structured internal financial, operational, and relationship data.
- relationship_notes_agent: Unstructured relationship-manager notes retrieved through FAISS.

Routing rules:
- Questions about public-company financials, valuation multiples, stock price/earnings, or
  macro/benchmark rates go to external_data_agent.
- Questions about structured internal metrics go to internal_data_agent.
- Questions about RM notes, client sentiment, meeting observations, or explicit
  RM-attributed risk flags go to relationship_notes_agent.
- Requests combining sources may be delegated to multiple agents.
- "Flagged at risk by the relationship manager" requires evidence from
  relationship_notes_agent. Structured relationship status or risk scores may
  corroborate the answer but may not replace RM-note evidence.
- Preserve note IDs and other source identifiers in the final answer.
- Clearly distinguish explicit source evidence from model inference."""

# Which MCP server(s) back each specialist -- for internal_data_agent/
# relationship_notes_agent, actually used by _load_specialist_tools to load
# that server's raw tool catalog. external_data_agent's entry is
# documentation only (which providers its five curated adapters ultimately
# call -- see agents/external_adapters.py): _load_specialist_tools never
# reads it for external_data_agent, since that specialist's tools are the
# fixed curated set, not a per-server union.
SPECIALIST_SERVERS: dict[EvidenceSourceAgent, list[str]] = {
    EvidenceSourceAgent.EXTERNAL_DATA_AGENT: ["fmp", "alpha_vantage", "fred"],
    EvidenceSourceAgent.INTERNAL_DATA_AGENT: ["internal_data"],
    EvidenceSourceAgent.RELATIONSHIP_NOTES_AGENT: ["relationship_notes"],
}

SPECIALIST_PROMPTS: dict[EvidenceSourceAgent, str] = {
    EvidenceSourceAgent.EXTERNAL_DATA_AGENT: (
        "You research public-company market data using exactly five tools, each already scoped to one "
        "purpose -- never any other MCP tool, and you have no access to the bank's own Supabase data or "
        "credentials:\n"
        "- fmp_get_financial_health: liquidity, leverage, and margin ratios (FMP).\n"
        "- fmp_get_valuation: enterprise value and valuation multiples, including debt capacity (FMP).\n"
        "- av_get_market_signal: company profile and recent price action (Alpha Vantage).\n"
        "- av_get_earnings_signal: recent earnings history (Alpha Vantage).\n"
        "- fred_get_rate_signal: a named benchmark/macro rate -- call this only when a macro or "
        "benchmark rate is actually relevant to the question, never by default.\n\n"
        "If the request includes a research plan, follow it: call the adapters it names, in light of "
        "the reason given for each, before considering any others. If no plan is given, use your own "
        "judgment, preferring the smallest set of non-duplicative signals that actually answers the "
        "question over calling every adapter.\n\n"
        "Every one of these tools already returns a pre-built evidence_code for each fact (e.g. "
        "FMP_XOM_NET_DEBT_TO_EBITDA_20251231) -- copy it verbatim in parentheses for every fact you "
        "report. You must never construct, alter, or guess an evidence code yourself; if a tool's "
        "response has no evidence_code for a fact, do not report that fact as cited evidence. Each tool "
        "also reports its own status (completed/no_data/unavailable/auth_error/rate_limited/timed_out) -- "
        "a completed call with no evidence found is a real, reportable fact (nothing material as of "
        "this date); anything else is a gap. State any such gap explicitly (e.g. \"FRED was unavailable; "
        "benchmark rate not checked\") rather than silently omitting the source or implying it was "
        "checked and clean.\n\n"
        "Report what each source actually says as an observed fact, separately from any interpretation "
        "-- never state that a metric's direction is inherently positive or negative (a rising "
        "debt-to-EBITDA ratio is a fact; whether it matters depends on the covenant and business "
        "context, which is the Synthesizer's job, not yours). Never conclude or imply that a borrower's "
        "credit quality is deteriorating from bank exposure alone, a maturity date alone, a price "
        "movement alone, or a relationship-risk flag alone -- credit-quality deterioration requires "
        "direct credit-quality evidence (a rating action, covenant breach, delinquency, or explicit "
        "credit-quality assessment), which these five tools mostly do not provide; report the raw "
        "metrics and let the Synthesizer draw that conclusion only if the evidence actually supports it. "
        "State missing or contradictory data explicitly rather than smoothing over it. Return no more "
        "than 10 material signals for a company, ranked by materiality and relevance."
    ),
    EvidenceSourceAgent.INTERNAL_DATA_AGENT: (
        "You answer questions about the bank's internal relationship with a company. Two generations "
        "of tools exist for this, and a single request never mixes them:\n\n"
        "- get_company_research_context: the current schema (target_companies/bank_credit_exposures/"
        "crm_deal_pipeline/internal_risk_flags) -- company identity/status/coverage lead, credit "
        "facilities (evidence_code prefix EXP_), CRM deal pipeline (DEAL_), and internal risk flags "
        "(RISKFLAG_). One call returns everything this schema has for a company.\n"
        "- get_relationship_history, get_products, get_opportunities, get_risk_assessment, "
        "get_client_interactions, search_internal_notes: the older schema (REL_/RELM_/PROD_/OPP_/"
        "RISK_/INT_/NOTE_ evidence codes) -- relationship health and revenue, banking products, the "
        "opportunity pipeline, risk assessments, and client interactions.\n\n"
        "If the task prompt tells you this request selected only the new internal schema, use "
        "get_company_research_context exclusively -- never call any tool from the older-schema list "
        "above for that request, even if get_company_research_context itself errors; report an error "
        "like that as a source/configuration problem instead of substituting an older-schema tool's "
        "data for it. Otherwise (no such instruction), use whichever tools the question actually "
        "calls for, from either generation.\n\n"
        "Every tool result includes an evidence_code field -- cite it verbatim in parentheses for "
        "every fact you report. Never omit it, substitute a date or description in its place, or "
        "construct/guess one yourself."
    ),
    EvidenceSourceAgent.RELATIONSHIP_NOTES_AGENT: RELATIONSHIP_NOTES_AGENT_PROMPT,
}

# Appended only to the structured-output specialist prompts (below), not the
# plain-text ones build_supervisor()/assistant chat use -- the instruction to
# report a real per-citation date only matters once something is actually
# asking for one field.
STRUCTURED_OUTPUT_ADDENDUM = (
    "\n\nReport your findings as structured evidence. For every evidence item, use the exact "
    "evidence_code from the tool result and the exact real date associated with it (as_of_date, "
    "note_date, observation_month, filing date, etc.) -- never today's date, never a placeholder. "
    "If a tool result has no clear date, omit that item rather than guessing a date.\n\n"
    "If any tool you called returns a JSON response with its own provider/status/message fields (this "
    "is how external_data_agent's five adapters report per-provider outcomes -- see their tool "
    "descriptions), report one entry per such call in provider_statuses with that exact provider and "
    "status, copied verbatim, plus its message if one was given -- never omitted just because the "
    "status wasn't 'completed'. Leave provider_statuses empty if no tool you called returns that shape."
)

# Process-wide cache: an agent's MCP tool catalog only needs loading once
# (mirrors mcp_client.py's own tool-definition cache), and there's no
# per-request/per-user state on the agent object itself to invalidate.
_specialist_cache: dict[EvidenceSourceAgent, object] = {}
_specialist_cache_lock = asyncio.Lock()

# Separate cache/lock for the response_format=SpecialistFindings variant --
# a distinct agent configuration from the plain-text one above, even though
# it shares the same tools and base prompt.
_structured_specialist_cache: dict[EvidenceSourceAgent, object] = {}
_structured_specialist_cache_lock = asyncio.Lock()


async def _load_specialist_tools(source_agent: EvidenceSourceAgent) -> list:
    """external_data_agent gets the five curated adapters from
    agents/external_adapters.py directly -- never the raw union of every
    FMP/Alpha Vantage/FRED MCP tool (that used to be built and de-duplicated
    here; a collision between two independent vendors' 26+112-tool
    catalogs, e.g. both exposing "company_dividends", was a real,
    observed failure mode of that approach, not a hypothetical one). Each
    curated adapter internally calls whichever real vendor tool backs it
    (mcp_client.call_tool_cached), so no MCP tool-loading round trip happens
    here for external_data_agent at all, and no collision handling is
    needed either -- the five names are hand-chosen and disjoint by
    construction.

    Every other specialist still loads its one server's raw tool catalog
    via mcp_client.load_tools, unchanged.
    """

    if source_agent == EvidenceSourceAgent.EXTERNAL_DATA_AGENT:
        return build_external_adapter_tools()

    server_names = SPECIALIST_SERVERS[source_agent]
    tools: list = []
    for name in server_names:
        tools.extend(await load_tools(name, cache_results=False))
    return tools


async def build_specialist(source_agent: EvidenceSourceAgent):
    """Build (or reuse) the single ReAct agent for one source, bound only to
    that source's own MCP tools -- no supervisor, no routing. This is what
    agents/research_execution.py calls for deterministic, per-(company,
    source) dispatch of a research request.
    """

    if source_agent in _specialist_cache:
        return _specialist_cache[source_agent]

    async with _specialist_cache_lock:
        if source_agent in _specialist_cache:  # re-check: another caller may have built it while we waited
            return _specialist_cache[source_agent]

        tools = await _load_specialist_tools(source_agent)
        agent = create_agent(
            chat_model(),
            tools,
            system_prompt=SPECIALIST_PROMPTS[source_agent],
            name=source_agent.value,
        )
        _specialist_cache[source_agent] = agent
        return agent


async def run_specialist(source_agent: EvidenceSourceAgent, prompt: str) -> str:
    """Invoke one specialist directly with one prompt, no supervisor routing."""

    agent = await build_specialist(source_agent)
    result = await agent.ainvoke({"messages": [{"role": "user", "content": prompt}]})
    return result["messages"][-1].content


async def build_structured_specialist(source_agent: EvidenceSourceAgent):
    """Same tools and domain prompt as build_specialist, but constrained to
    return SpecialistFindings as its final output (LangGraph's
    response_format) instead of free text -- this is what lets
    agents/research_execution.py get real per-citation evidence dates
    straight from the tool results the agent already saw, instead of
    regex-scraping a date-less prose answer. A separate agent/cache from
    build_specialist: assistant chat (build_supervisor/run) keeps using the
    plain-text one, unchanged.
    """

    if source_agent in _structured_specialist_cache:
        return _structured_specialist_cache[source_agent]

    async with _structured_specialist_cache_lock:
        if source_agent in _structured_specialist_cache:
            return _structured_specialist_cache[source_agent]

        tools = await _load_specialist_tools(source_agent)
        agent = create_agent(
            chat_model(),
            tools,
            system_prompt=SPECIALIST_PROMPTS[source_agent] + STRUCTURED_OUTPUT_ADDENDUM,
            name=source_agent.value,
            response_format=SpecialistFindings,
        )
        _structured_specialist_cache[source_agent] = agent
        return agent


async def run_structured_specialist(source_agent: EvidenceSourceAgent, prompt: str) -> SpecialistFindings:
    """Invoke one specialist directly, returning SpecialistFindings instead
    of a free-text answer. Used by agents/research_execution.py's
    deterministic dispatch; never by assistant chat."""

    agent = await build_structured_specialist(source_agent)
    result = await agent.ainvoke({"messages": [{"role": "user", "content": prompt}]})
    return result["structured_response"]


async def build_supervisor():
    agents = [await build_specialist(source_agent) for source_agent in SPECIALIST_SERVERS]
    return create_supervisor(
        agents=agents,
        model=chat_model(),
        prompt=SUPERVISOR_PROMPT,
    ).compile()


async def run(question: str, history: list[dict] | None = None) -> str:
    supervisor = await build_supervisor()
    messages = [*(history or []), {"role": "user", "content": question}]
    result = await supervisor.ainvoke({"messages": messages})
    return result["messages"][-1].content


if __name__ == "__main__":
    question = "What did Apple report as revenue last quarter?"
    print(asyncio.run(run(question)))
