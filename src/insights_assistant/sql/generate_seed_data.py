"""Deterministic synthetic seed-data generator for internal_tables.sql.

Everything here is fully fictional: company identities are real (for EDGAR
ticker lookups), but all relationship, transaction, revenue, opportunity,
risk, and interaction data is synthetic and generated from a fixed seed so
the resulting dataset -- and the ground-truth scenarios built on top of it --
are 100% reproducible.

Run: python -m insights_assistant.sql.generate_seed_data
Writes: src/insights_assistant/sql/seed_data.sql
"""

import random
from datetime import date, timedelta
from pathlib import Path

SEED = 1337
END_MONTH = date(2026, 7, 1)  # most recent fully-observed month in the series
OUTPUT_PATH = Path(__file__).parent / "seed_data.sql"

COMPANIES = [
    {"code": "WMT", "name": "Walmart", "ticker": "WMT", "industry": "Retail", "sector": "Consumer Staples"},
    {"code": "AMZN", "name": "Amazon", "ticker": "AMZN", "industry": "E-Commerce & Cloud Services", "sector": "Consumer Discretionary"},
    {"code": "AAPL", "name": "Apple", "ticker": "AAPL", "industry": "Consumer Electronics", "sector": "Technology"},
    {"code": "UNH", "name": "UnitedHealth Group", "ticker": "UNH", "industry": "Managed Health Care", "sector": "Health Care"},
    {"code": "CVS", "name": "CVS Health", "ticker": "CVS", "industry": "Health Care & Pharmacy", "sector": "Health Care"},
    {"code": "XOM", "name": "Exxon Mobil", "ticker": "XOM", "industry": "Oil & Gas", "sector": "Energy"},
    {"code": "GOOGL", "name": "Alphabet", "ticker": "GOOGL", "industry": "Internet Services", "sector": "Technology"},
    {"code": "MCK", "name": "McKesson", "ticker": "MCK", "industry": "Health Care Distribution", "sector": "Health Care"},
    {"code": "COR", "name": "Cencora", "ticker": "COR", "industry": "Health Care Distribution", "sector": "Health Care"},
    {"code": "COST", "name": "Costco", "ticker": "COST", "industry": "Wholesale Retail", "sector": "Consumer Staples"},
]

RM_NAMES = ["Dana Whitfield", "Marcus Ibe", "Priya Raman", "Colin Ashford", "Renata Souza",
            "Theo Baptiste", "Naomi Kessler", "Julian Marsh", "Fiona Ondrej", "Grant Elias"]
EXEC_SPONSOR_NAMES = ["Wendell Cho", "Ingrid Falk", "Marcus Delaine", "Sofia Bregman", "Hollis Yamada",
                       "Petra Lindqvist", "Aaron Vance", "Camille Duarte", "Noor Al-Sayed", "Desmond Root"]

ALL_PRODUCTS = ["payments", "treasury_services", "lending", "investment_banking",
                "capital_markets", "fx", "trade_finance", "liquidity_management", "custody"]

# ---------------------------------------------------------------------------
# 1. Deterministic tier + scenario assignment (reproduces the approved plan)
# ---------------------------------------------------------------------------

def assign_tiers_and_scenarios():
    rng = random.Random(SEED)
    shuffled = COMPANIES[:]
    rng.shuffle(shuffled)
    tier1_codes = {c["code"] for c in shuffled[:5]}

    scenarios = ["EXT_POS_INT_POS", "EXT_POS_INT_NEG", "EXT_NEG_INT_OPP",
                 "EXT_NEG_INT_NEG", "EXT_SIG_INT_NEUTRAL", "EXT_SIG_INSUFFICIENT_DATA"]
    rng2 = random.Random(SEED + 1)
    pool = scenarios + rng2.sample(scenarios, 4)
    rng2.shuffle(pool)
    order = COMPANIES[:]
    rng2.shuffle(order)
    scenario_by_code = {c["code"]: s for c, s in zip(order, pool)}

    for c in COMPANIES:
        c["tier"] = "tier_1" if c["code"] in tier1_codes else "tier_2"
        c["scenario"] = scenario_by_code[c["code"]]

    assert {c["code"] for c in COMPANIES if c["tier"] == "tier_1"} == {"WMT", "UNH", "MCK", "AAPL", "AMZN"}


assign_tiers_and_scenarios()

# ---------------------------------------------------------------------------
# 2. Per-company financial/relationship profile
#    segments: list of (n_months, rev_start, rev_end, pipe_start, pipe_end,
#                        risk_start, risk_end, trend_label) summing to 24
# ---------------------------------------------------------------------------

PROFILES = {
    "AAPL": dict(
        relationship_strength="strong", relationship_status="strong",
        current_annual_revenue=165_000_000, prior_year_revenue=139_830_000,
        transaction_volume_ytd=2_450_000_000, relationship_start_date=date(2014, 3, 1),
        segments=[
            (12, 10.5, 12.6, 50, 68, 24, 21, "slow_growth"),
            (6, 12.6, 13.1, 68, 76, 21, 19, "stable"),
            (6, 13.1, 13.75, 76, 95, 19, 16, "rapid_growth"),
        ],
        products=[
            ("payments", 42_000_000, "active", "rapid_growth"),
            ("treasury_services", 28_000_000, "active", "growing"),
            ("fx", 21_000_000, "active", "stable"),
            ("custody", 19_000_000, "active", "growing"),
            ("investment_banking", 24_000_000, "active", "rapid_growth"),
            ("capital_markets", 17_000_000, "active", "growing"),
            ("liquidity_management", 14_000_000, "pilot", "rapid_growth"),
        ],
        flagship_opportunity=dict(
            name="International services expansion financing", value=48_000_000, stage="negotiation",
            probability_pct=70, strategic_importance="critical", status="active",
            competitive_pressure="low", competitor_name=None,
        ),
        extra_opportunities=[
            ("Custody mandate expansion", 12_000_000, "proposal", 55, "high", "active", "low", None),
            ("Supply-chain FX hedging program", 9_000_000, "qualification", 40, "medium", "active", "none", None),
        ],
        flagship_interaction=dict(
            topic="expansion_plans", sentiment="positive",
            summary="QBR covering accelerated services expansion into new international markets; client requested "
                     "expanded custody and FX hedging capacity to support the rollout.",
        ),
        flagship_note=(
            "Met with Apple's corporate treasury team this week to walk through the international services "
            "expansion they announced. The energy in the room was notably different from six months ago -- "
            "they are moving fast and want a banking partner who can scale with them, not just process volume. "
            "Treasury flagged that current custody capacity will need to roughly double over the next two "
            "quarters to support new market entities, and they specifically asked whether we could accelerate "
            "onboarding for FX hedging given the number of new currency exposures the expansion creates. I "
            "walked them through our investment banking group's proposal for financing the rollout and got a "
            "strongly positive reaction; they want a term sheet within three weeks. Executive sponsor confirmed "
            "this is now a board-visible initiative internally, which raises the strategic importance of "
            "getting this right. No competitive mentions in the room, which is a good sign we are still the "
            "preferred partner here. Recommend fast-tracking the custody expansion proposal and looping in "
            "capital markets given the size of financing being discussed. This is one of the strongest "
            "expansion signals we have seen from this relationship in the past two years."
        ),
        risk_comment_recent="Risk profile continues to improve as recurring services revenue diversifies away from transaction-linked volume.",
        external_signal=dict(
            headline="Apple announces accelerated international services and retail expansion",
            description="Apple detailed plans to expand services and retail operations into several new "
                         "international markets over the next two fiscal years, citing strong demand for "
                         "subscription and services offerings.",
            character="positive",
        ),
        ground_truth=dict(
            expected_internal_signal="Rising relationship revenue, expanding pipeline tied directly to the expansion, new critical-importance opportunity, positive expansion-focused meeting note",
            expected_signal_alignment="CONFIRMING",
            expected_insight_category="OPPORTUNITY",
            expected_relevance_level="HIGH",
            expected_relationship_interpretation=(
                "Apple's public expansion announcement is mirrored internally: relationship revenue is "
                "accelerating, the pipeline has grown sharply on the back of a large financing opportunity "
                "tied directly to the expansion, and the most recent client meeting confirms the bank is "
                "positioned as a preferred partner for the rollout. This is a high-confidence expansion "
                "opportunity, not just a public headline."
            ),
            expected_action="SURFACE",
            explanation="External and internal signals confirm each other strongly across revenue, pipeline, an active opportunity, and a recent client meeting -- a clean confirming case.",
        ),
    ),
    "AMZN": dict(
        relationship_strength="at_risk", relationship_status="at_risk",
        current_annual_revenue=140_000_000, prior_year_revenue=175_000_000,
        transaction_volume_ytd=1_980_000_000, relationship_start_date=date(2012, 6, 1),
        segments=[
            (12, 14.4, 14.6, 55, 58, 30, 32, "stable"),
            (6, 14.6, 13.8, 58, 50, 32, 45, "declining"),
            (6, 13.8, 11.67, 50, 37.7, 45, 68, "sudden_deterioration"),
        ],
        products=[
            ("payments", 38_000_000, "active", "declining"),
            ("treasury_services", 26_000_000, "active", "at_risk"),
            ("trade_finance", 22_000_000, "active", "declining"),
            ("lending", 18_000_000, "active", "stable"),
            ("fx", 20_000_000, "active", "growing"),
            ("capital_markets", 16_000_000, "active", "declining"),
        ],
        flagship_opportunity=dict(
            name="Warehouse network capital markets refinancing", value=32_000_000, stage="closed_lost",
            probability_pct=0, strategic_importance="critical", status="lost",
            competitive_pressure="high", competitor_name="Meridian Capital Partners",
        ),
        extra_opportunities=[
            ("Trade finance renewal", 8_000_000, "stalled", 25, "medium", "stalled", "moderate", "Meridian Capital Partners"),
            ("Payments platform upsell", 6_500_000, "prospecting", 20, "low", "active", "low", None),
        ],
        flagship_interaction=dict(
            topic="competitor_activity", sentiment="negative",
            summary="Follow-up call after losing the warehouse-network refinancing mandate; client confirmed "
                     "Meridian Capital Partners is now embedded in three additional workstreams.",
        ),
        flagship_note=(
            "Difficult call today following the confirmation that we lost the warehouse-network refinancing "
            "mandate to Meridian Capital Partners. This is the second competitive loss with this client in "
            "the past two quarters and the pattern is becoming concerning. Their treasury lead was candid that "
            "Meridian has been more aggressive on pricing and, more worryingly, has staffed a dedicated "
            "coverage team that meets with Amazon's logistics finance group monthly -- something we have not "
            "matched. Transaction volumes on our core payments book are still solid, but treasury services "
            "revenue has been declining for three straight quarters and the trade finance renewal is now "
            "stalled pending a competing proposal. On a positive note, the FX desk relationship remains "
            "strong and that product line is actually growing, so this is not a uniform collapse -- it looks "
            "more like a competitive incursion specifically around lending and capital markets. Recommend an "
            "executive-to-executive relationship review before the next renewal cycle; we risk losing "
            "meaningful additional wallet share if Meridian's coverage model continues to outpace ours here."
        ),
        risk_comment_recent="Relationship risk trending sharply worse following a second consecutive competitive loss; concentration in fewer active products increases exposure to further share loss.",
        external_signal=dict(
            headline="Amazon announces logistics network restructuring and cost-reduction program",
            description="Amazon disclosed a multi-quarter restructuring of its logistics and fulfillment "
                         "network aimed at reducing operating costs, including facility consolidations.",
            character="negative",
        ),
        ground_truth=dict(
            expected_internal_signal="Declining relationship revenue, sharply shrinking pipeline, a lost critical opportunity to a named competitor, and a negative meeting note describing expanding competitor coverage -- despite one product (FX) still growing",
            expected_signal_alignment="CONFIRMING",
            expected_insight_category="RELATIONSHIP_RISK",
            expected_relevance_level="HIGH",
            expected_relationship_interpretation=(
                "Amazon's public restructuring lines up with a deteriorating internal relationship: revenue "
                "and pipeline are both down sharply, a large refinancing mandate was just lost to a named "
                "competitor, and the most recent note describes that competitor expanding its footprint "
                "further. FX is a bright spot, but it does not offset the broader risk pattern."
            ),
            expected_action="SURFACE",
            explanation="Multiple independent evidence types (revenue trend, pipeline, a lost named-competitor opportunity, and a negative note) all point the same direction, with one deliberately conflicting data point (FX growth) that a naive single-field rule would miss.",
        ),
    ),
    "UNH": dict(
        relationship_strength="moderate", relationship_status="developing_opportunity",
        current_annual_revenue=118_000_000, prior_year_revenue=115_700_000,
        transaction_volume_ytd=1_240_000_000, relationship_start_date=date(2016, 9, 1),
        segments=[
            (12, 9.6, 9.7, 38, 40, 40, 40, "stable"),
            (9, 9.7, 9.8, 40, 42, 40, 38, "stable"),
            (3, 9.8, 9.83, 42, 52, 38, 35, "recovering"),
        ],
        products=[
            ("treasury_services", 30_000_000, "active", "stable"),
            ("payments", 26_000_000, "active", "stable"),
            ("lending", 22_000_000, "active", "stable"),
            ("liquidity_management", 18_000_000, "active", "growing"),
            ("investment_banking", 12_000_000, "pilot", "growing"),
        ],
        flagship_opportunity=dict(
            name="Regulatory transformation advisory mandate", value=30_000_000, stage="proposal",
            probability_pct=50, strategic_importance="high", status="active",
            competitive_pressure="moderate", competitor_name=None,
        ),
        extra_opportunities=[
            ("Liquidity management platform expansion", 9_000_000, "qualification", 45, "medium", "active", "none", None),
            ("Working-capital facility increase", 7_500_000, "prospecting", 30, "low", "active", "low", None),
        ],
        flagship_interaction=dict(
            topic="strategic_opportunity", sentiment="positive",
            summary="CFO office reached out proactively to scope advisory support for regulatory-driven "
                     "restructuring; requested a proposal covering financing and transformation advisory.",
        ),
        flagship_note=(
            "Notable inbound outreach from UnitedHealth's CFO office this week, prompted by the regulatory "
            "scrutiny and cost-reduction program they announced publicly. Rather than a defensive posture, "
            "the tone was opportunistic -- they are looking for a banking partner to help structure financing "
            "and provide transformation advisory as they reorganize segments of the business in response to "
            "the regulatory environment. This is a meaningful shift from prior conversations, which had been "
            "largely transactional around treasury services. Core relationship revenue has been essentially "
            "flat for the past six quarters, so this proposal represents genuine incremental opportunity "
            "rather than defense of an existing book. There is moderate competitive pressure -- they mentioned "
            "at least one other bank is also being asked to scope a similar proposal -- so responsiveness "
            "matters here. Recommend assembling a joint treasury and investment banking team to move quickly; "
            "the executive sponsor relationship is strong and this could meaningfully deepen the relationship "
            "tier if we win the mandate."
        ),
        risk_comment_recent="Risk profile stable to slightly improving; new advisory engagement is not yet reflected in exposure but would diversify revenue away from transactional-only products.",
        external_signal=dict(
            headline="UnitedHealth Group announces regulatory scrutiny and cost-reduction restructuring",
            description="UnitedHealth Group disclosed heightened regulatory scrutiny of certain business "
                         "segments alongside a cost-reduction and restructuring program.",
            character="negative",
        ),
        ground_truth=dict(
            expected_internal_signal="Flat core revenue but a new high-value advisory/financing opportunity directly tied to the restructuring, plus a proactive positive client outreach",
            expected_signal_alignment="CONTRADICTORY",
            expected_insight_category="OPPORTUNITY",
            expected_relevance_level="MEDIUM",
            expected_relationship_interpretation=(
                "UnitedHealth's public restructuring reads negatively on its face, but internally it has "
                "produced a proactive, high-value advisory opportunity rather than relationship deterioration. "
                "The bank should treat this as an opportunity to deepen the relationship through transformation "
                "advisory, not a risk signal."
            ),
            expected_action="SURFACE",
            explanation="Public negative news combined with a genuine internal opportunity requires the agent to override the naive negative-headline-implies-risk pattern.",
        ),
    ),
    "MCK": dict(
        relationship_strength="moderate", relationship_status="stable",
        current_annual_revenue=95_000_000, prior_year_revenue=92_200_000,
        transaction_volume_ytd=880_000_000, relationship_start_date=date(2018, 1, 1),
        segments=[
            (12, 7.6, 7.75, 25, 26, 22, 22, "stable"),
            (12, 7.75, 7.92, 26, 28, 22, 20, "stable"),
        ],
        products=[
            ("treasury_services", 24_000_000, "active", "stable"),
            ("payments", 20_000_000, "active", "stable"),
            ("lending", 18_000_000, "active", "stable"),
            ("trade_finance", 15_000_000, "active", "stable"),
        ],
        flagship_opportunity=dict(
            name="Treasury services renewal", value=10_000_000, stage="negotiation",
            probability_pct=80, strategic_importance="medium", status="active",
            competitive_pressure="none", competitor_name=None,
        ),
        extra_opportunities=[
            ("Trade finance line increase", 5_000_000, "qualification", 35, "low", "active", "none", None),
        ],
        flagship_interaction=dict(
            topic="renewal_discussion", sentiment="neutral",
            summary="Routine annual treasury services renewal discussion; no mention of the recently "
                     "announced leadership transition.",
        ),
        flagship_note=(
            "Held the annual treasury services renewal check-in with McKesson's finance team today. Terms "
            "discussion was routine and cooperative, with an expected close in the next few weeks at broadly "
            "similar pricing to last year. I specifically asked whether the recently announced executive "
            "leadership change was expected to affect banking relationships or treasury strategy, and the "
            "team indicated no changes are anticipated on their side -- the transition is being handled at "
            "the corporate level and has not touched the treasury or finance organization we work with. "
            "Product usage across treasury services, payments, lending, and trade finance has been essentially "
            "flat for two years, which reflects a mature, stable relationship rather than one that is actively "
            "expanding or contracting. No competitive activity noted. This is a low-drama, steady account; "
            "recommend continuing standard relationship cadence rather than any special escalation tied to "
            "the leadership news."
        ),
        risk_comment_recent="Risk profile stable and low; mature relationship with consistent product usage and no exposure concentration concerns.",
        external_signal=dict(
            headline="McKesson announces executive leadership transition",
            description="McKesson announced a transition in its executive leadership team, effective next "
                         "fiscal quarter, as part of a planned succession process.",
            character="significant_neutral",
        ),
        ground_truth=dict(
            expected_internal_signal="Flat revenue, routine renewal in progress, and an explicit note that the leadership change has no bearing on the treasury relationship",
            expected_signal_alignment="NEUTRAL",
            expected_insight_category="NO_MATERIAL_IMPACT",
            expected_relevance_level="LOW",
            expected_relationship_interpretation=(
                "The leadership transition is publicly significant for McKesson but has no material connection "
                "to the bank's relationship, which remains flat, stable, and unaffected per the most recent "
                "client conversation."
            ),
            expected_action="REVIEW",
            explanation="Tests whether the agent avoids over-indexing on a publicly significant event that internal evidence explicitly shows is not relevant to the relationship.",
        ),
    ),
    "WMT": dict(
        relationship_strength="strong", relationship_status="strong",
        current_annual_revenue=180_000_000, prior_year_revenue=165_100_000,
        transaction_volume_ytd=3_100_000_000, relationship_start_date=date(2010, 4, 1),
        segments=[
            (12, 13.6, 14.3, 55, 62, 20, 19, "slow_growth"),
            (12, 14.3, 15.0, 62, 70, 19, 17, "slow_growth"),
        ],
        products=[
            ("payments", 45_000_000, "active", "growing"),
            ("treasury_services", 34_000_000, "active", "stable"),
            ("liquidity_management", 28_000_000, "active", "growing"),
            ("trade_finance", 26_000_000, "active", "stable"),
            ("fx", 22_000_000, "active", "stable"),
            ("lending", 18_000_000, "active", "stable"),
            ("capital_markets", 7_000_000, "pilot", "growing"),
        ],
        flagship_opportunity=dict(
            name="General corporate financing facility", value=40_000_000, stage="qualification",
            probability_pct=35, strategic_importance="medium", status="active",
            competitive_pressure="low", competitor_name=None,
        ),
        extra_opportunities=[
            ("Payments platform international rollout", 15_000_000, "proposal", 45, "medium", "active", "low", None),
            ("Liquidity sweep structure upgrade", 6_000_000, "prospecting", 20, "low", "active", "none", None),
        ],
        flagship_interaction=dict(
            topic="investment_priorities", sentiment="neutral",
            summary="Standard quarterly relationship review covering core treasury and payments usage; "
                     "capital-markets team was not present and the recent financing activity was not discussed "
                     "in detail.",
        ),
        flagship_note=(
            "Quarterly relationship review with Walmart's regional treasury team went well overall -- the "
            "core banking relationship remains one of our strongest by revenue, with steady growth across "
            "payments, treasury services, and liquidity management over the past two years. That said, this "
            "call was specifically with the regional treasury contacts, not the corporate capital-markets or "
            "corporate development functions, so I do not have direct visibility into how the recently "
            "reported large capital-markets activity is being financed or which banks are involved. The "
            "attendees present were not able to speak to it and I did not want to press given the audience. "
            "The existing corporate financing facility opportunity in our pipeline is unrelated and moving "
            "along its own timeline. Given the size and profile of the reported activity, it is worth getting "
            "a meeting with the corporate development or capital-markets contacts specifically to understand "
            "whether there is a role for us, but I do not have that evidence yet from this call."
        ),
        risk_comment_recent="Risk profile low and stable; strong, well-diversified product usage across a long-tenured relationship.",
        external_signal=dict(
            headline="Walmart announces significant corporate capital-markets activity",
            description="Walmart disclosed a significant corporate capital-markets transaction as part of its "
                         "broader capital allocation strategy.",
            character="significant_neutral",
        ),
        ground_truth=dict(
            expected_internal_signal="Strong, healthy overall relationship, but no interactions, notes, or opportunities in the retrieved evidence specifically touch the reported capital-markets activity",
            expected_signal_alignment="INSUFFICIENT",
            expected_insight_category="INSUFFICIENT_EVIDENCE",
            expected_relevance_level="MEDIUM",
            expected_relationship_interpretation=(
                "Walmart's relationship is strong overall, but the retrieved internal evidence has no direct "
                "coverage of the specific capital-markets activity referenced in the external signal -- the "
                "most recent note explicitly says the relevant contacts were not part of the conversation. "
                "The agent should not fabricate a personalized conclusion about this specific event from "
                "general relationship health."
            ),
            expected_action="REVIEW",
            explanation="Tests whether the agent correctly recognizes that broad relationship strength is not the same as targeted evidence about a specific external event, and flags for human follow-up instead of overstating confidence.",
        ),
    ),
    "XOM": dict(
        relationship_strength="at_risk", relationship_status="at_risk",
        current_annual_revenue=62_000_000, prior_year_revenue=76_000_000,
        transaction_volume_ytd=640_000_000, relationship_start_date=date(2013, 11, 1),
        segments=[
            (12, 6.2, 6.35, 28, 30, 35, 38, "stable"),
            (8, 6.35, 5.7, 30, 22, 38, 55, "declining"),
            (4, 5.7, 5.17, 22, 18, 55, 66, "sudden_deterioration"),
        ],
        products=[
            ("trade_finance", 18_000_000, "active", "declining"),
            ("treasury_services", 16_000_000, "active", "declining"),
            ("fx", 14_000_000, "active", "stable"),
            ("lending", 14_000_000, "active", "at_risk"),
        ],
        flagship_opportunity=dict(
            name="Capital markets bond issuance mandate", value=22_000_000, stage="closed_lost",
            probability_pct=0, strategic_importance="high", status="lost",
            competitive_pressure="high", competitor_name="Harrow & Vance Capital",
        ),
        extra_opportunities=[
            ("Trade finance renewal", 4_500_000, "stalled", 20, "medium", "stalled", "moderate", "Harrow & Vance Capital"),
        ],
        flagship_interaction=dict(
            topic="competitor_activity", sentiment="negative",
            summary="Post-mortem on the lost bond issuance mandate; client confirmed Harrow & Vance Capital "
                     "is now leading two additional financing conversations.",
        ),
        flagship_note=(
            "Sobering conversation with Exxon Mobil's corporate finance team following confirmation that we "
            "lost the bond issuance mandate to Harrow & Vance Capital. This is despite the strong earnings "
            "and expansion news the company announced publicly this quarter -- if anything, that public "
            "strength appears to be benefiting our competitor rather than us. The client was direct that "
            "Harrow & Vance has been more aggressive on both pricing and coverage intensity, and is now also "
            "leading two other financing conversations that used to be ours to lose. Relationship revenue has "
            "been declining for three consecutive quarters and the trade finance renewal is now stalled "
            "pending a competing term sheet. Risk scores have moved up meaningfully as our share of wallet "
            "concentrates into fewer, smaller products. This is a clear case where the company's public good "
            "news is not translating into a stronger relationship for us -- quite the opposite. Recommend an "
            "urgent relationship-risk review and a senior banker introduction before we lose further ground."
        ),
        risk_comment_recent="Relationship risk trending sharply worse; a second lost mandate to the same named competitor within two quarters signals accelerating share loss despite the client's public strength.",
        external_signal=dict(
            headline="Exxon Mobil reports strong quarterly earnings and announces expansion plans",
            description="Exxon Mobil reported quarterly earnings above expectations and announced plans to "
                         "expand production capacity at several facilities.",
            character="positive",
        ),
        ground_truth=dict(
            expected_internal_signal="Declining relationship revenue, pipeline down sharply, a lost mandate to a named competitor, and a note identifying that competitor gaining further share",
            expected_signal_alignment="CONTRADICTORY",
            expected_insight_category="RELATIONSHIP_RISK",
            expected_relevance_level="HIGH",
            expected_relationship_interpretation=(
                "Exxon Mobil's public growth is positive, but the bank's position with the company is "
                "deteriorating -- expansion could benefit competitors unless the relationship is strengthened."
            ),
            expected_action="SURFACE",
            explanation="This is the flagship contradictory-alignment scenario: strong public news paired with a genuinely weakening internal relationship, requiring synthesis across revenue, pipeline, a lost opportunity, and a note naming the competitor.",
        ),
    ),
    "GOOGL": dict(
        relationship_strength="at_risk", relationship_status="at_risk",
        current_annual_revenue=54_000_000, prior_year_revenue=69_200_000,
        transaction_volume_ytd=520_000_000, relationship_start_date=date(2017, 2, 1),
        segments=[
            (12, 5.6, 5.4, 21.8, 19, 40, 45, "declining"),
            (12, 5.4, 4.5, 19, 12, 45, 62, "declining"),
        ],
        products=[
            ("payments", 15_000_000, "active", "declining"),
            ("fx", 12_000_000, "active", "stable"),
            ("treasury_services", 13_000_000, "active", "declining"),
            ("investment_banking", 14_000_000, "active", "at_risk"),
        ],
        flagship_opportunity=dict(
            name="Data-center financing facility", value=18_000_000, stage="closed_lost",
            probability_pct=0, strategic_importance="high", status="lost",
            competitive_pressure="high", competitor_name="Bellcrest Financial",
        ),
        extra_opportunities=[
            ("FX hedging program renewal", 4_000_000, "stalled", 25, "low", "stalled", "moderate", None),
        ],
        flagship_interaction=dict(
            topic="relationship_concerns", sentiment="negative",
            summary="Client raised concerns about responsiveness on the data-center financing proposal; "
                     "confirmed the mandate went to Bellcrest Financial.",
        ),
        flagship_note=(
            "Alphabet's infrastructure finance team confirmed today that the data-center financing facility "
            "went to Bellcrest Financial, citing faster turnaround on term sheets as the deciding factor. This "
            "follows the antitrust ruling and investment pullback the company announced publicly, and "
            "internally we are seeing the relationship soften in parallel rather than in isolation -- revenue "
            "has declined for four consecutive quarters and the pipeline has contracted by nearly half. The "
            "one relative bright spot is the FX product line, which has held roughly flat while everything "
            "else has weakened, suggesting the erosion is concentrated in financing-related products rather "
            "than transactional banking broadly. Sentiment on this call was clearly negative; the client used "
            "the word \"frustrated\" twice regarding our response times. Recommend a structured escalation "
            "with a committed response-time SLA before the next financing conversation, or we risk this "
            "becoming a broader relationship exit rather than a single lost deal."
        ),
        risk_comment_recent="Risk trending worse in line with declining public sentiment; concentration risk rising as financing-related products erode faster than transactional banking.",
        external_signal=dict(
            headline="Alphabet faces adverse antitrust ruling and announces investment pullback",
            description="Alphabet disclosed an adverse antitrust ruling in a key market and announced a "
                         "pullback in planned capital investment as it reassesses strategy.",
            character="negative",
        ),
        ground_truth=dict(
            expected_internal_signal="Declining revenue and pipeline, a lost financing mandate to a named competitor, and a negative note citing responsiveness as the cause -- with FX holding flat as a partial counterpoint",
            expected_signal_alignment="CONFIRMING",
            expected_insight_category="RELATIONSHIP_RISK",
            expected_relevance_level="HIGH",
            expected_relationship_interpretation=(
                "Alphabet's public setback is mirrored by a genuinely weakening internal relationship, with a "
                "specific, addressable root cause (response-time competitiveness) rather than a vague "
                "downturn."
            ),
            expected_action="SURFACE",
            explanation="A second confirming risk case with a different evidence combination (responsiveness-driven loss vs. pricing-driven loss for Exxon) to test the agent isn't pattern-matching on a single fixed evidence template.",
        ),
    ),
    "COST": dict(
        relationship_strength="developing", relationship_status="developing_opportunity",
        current_annual_revenue=48_000_000, prior_year_revenue=49_500_000,
        transaction_volume_ytd=410_000_000, relationship_start_date=date(2019, 8, 1),
        segments=[
            (12, 4.15, 4.05, 22, 24, 30, 30, "stable"),
            (9, 4.05, 3.95, 24, 25, 30, 28, "stable"),
            (3, 3.95, 4.0, 25, 31, 28, 25, "recovering"),
        ],
        products=[
            ("payments", 16_000_000, "active", "stable"),
            ("treasury_services", 14_000_000, "active", "stable"),
            ("liquidity_management", 10_000_000, "active", "growing"),
            ("trade_finance", 8_000_000, "active", "stable"),
        ],
        flagship_opportunity=dict(
            name="Working-capital liquidity advisory", value=25_000_000, stage="proposal",
            probability_pct=55, strategic_importance="high", status="active",
            competitive_pressure="moderate", competitor_name=None,
        ),
        extra_opportunities=[
            ("Trade finance capacity increase", 5_500_000, "qualification", 30, "medium", "active", "none", None),
        ],
        flagship_interaction=dict(
            topic="strategic_opportunity", sentiment="positive",
            summary="CFO team requested a liquidity and working-capital advisory proposal in direct response "
                     "to the margin-compression pressures discussed publicly.",
        ),
        flagship_note=(
            "Productive call with Costco's finance leadership following their public comments on margin "
            "compression and cost pressure. Rather than pulling back, they proactively asked for a proposal "
            "on working-capital and liquidity advisory -- they want to optimize cash conversion cycles and "
            "explore structured liquidity solutions as a direct response to the margin pressure. This is a "
            "meaningful shift from the largely transactional relationship we have had for the past two years, "
            "where revenue has been flat to slightly declining. There is moderate competitive pressure since "
            "they mentioned exploring options with at least one other regional bank, so timeliness on our "
            "proposal matters. If we win this, it would be a genuine step up in relationship depth and "
            "product diversification beyond core payments and treasury services. Recommend prioritizing the "
            "advisory proposal this month while the CFO team's attention is on this initiative."
        ),
        risk_comment_recent="Risk stable; a new advisory opportunity, if won, would improve diversification without materially increasing exposure.",
        external_signal=dict(
            headline="Costco cites margin compression amid rising cost pressures",
            description="Costco disclosed margin compression driven by rising input and labor costs, and "
                         "outlined cost-management initiatives for the coming fiscal year.",
            character="negative",
        ),
        ground_truth=dict(
            expected_internal_signal="Flat-to-slightly-declining core revenue, but a new high-value liquidity advisory opportunity directly requested by the client in response to the margin pressure",
            expected_signal_alignment="CONTRADICTORY",
            expected_insight_category="OPPORTUNITY",
            expected_relevance_level="MEDIUM",
            expected_relationship_interpretation=(
                "Costco's public margin pressure has created a genuine advisory opportunity rather than "
                "relationship risk -- the client is proactively seeking liquidity solutions, and the bank "
                "should pursue this as a chance to deepen the relationship."
            ),
            expected_action="SURFACE",
            explanation="A second contrarian-opportunity case (negative headline, positive internal signal) with different mechanics than UnitedHealth's, to test generalization rather than template matching.",
        ),
    ),
    "CVS": dict(
        relationship_strength="moderate", relationship_status="stable",
        current_annual_revenue=58_000_000, prior_year_revenue=55_800_000,
        transaction_volume_ytd=490_000_000, relationship_start_date=date(2015, 5, 1),
        segments=[
            (12, 4.5, 4.65, 13, 14, 25, 24, "stable"),
            (12, 4.65, 4.83, 14, 15, 24, 22, "stable"),
        ],
        products=[
            ("payments", 22_000_000, "active", "stable"),
            ("treasury_services", 18_000_000, "active", "stable"),
            ("lending", 12_000_000, "active", "stable"),
            ("fx", 6_000_000, "active", "stable"),
        ],
        flagship_opportunity=dict(
            name="Payments platform renewal", value=8_000_000, stage="negotiation",
            probability_pct=75, strategic_importance="medium", status="active",
            competitive_pressure="none", competitor_name=None,
        ),
        extra_opportunities=[
            ("Treasury services cross-sell", 3_000_000, "prospecting", 20, "low", "active", "none", None),
        ],
        flagship_interaction=dict(
            topic="product_discussion", sentiment="neutral",
            summary="Routine payments platform renewal discussion; retail footprint changes were mentioned "
                     "only in passing and do not affect current banking services.",
        ),
        flagship_note=(
            "Standard payments platform renewal conversation with CVS Health's treasury operations team. "
            "Terms discussion was straightforward with an expected close in the next few weeks. I asked "
            "directly about the retail footprint changes they announced publicly and whether that would "
            "affect banking service volumes; the team said the changes are concentrated in store operations "
            "and real estate, and are not expected to materially change treasury or payments volumes with us. "
            "Product usage across payments, treasury services, and lending has been flat and steady for over "
            "two years -- this remains a low-complexity, stable relationship. No competitive activity or "
            "concerns raised. Recommend proceeding with standard renewal terms and no special escalation "
            "related to the retail footprint news."
        ),
        risk_comment_recent="Risk low and stable; consistent product usage with no indication the recent public announcement affects banking volumes.",
        external_signal=dict(
            headline="CVS Health announces significant changes to retail store footprint",
            description="CVS Health announced plans to significantly restructure its retail store footprint "
                         "over the next 18 months as part of a broader operating model shift.",
            character="significant_neutral",
        ),
        ground_truth=dict(
            expected_internal_signal="Flat, stable revenue and an explicit note that the footprint changes do not affect banking volumes",
            expected_signal_alignment="NEUTRAL",
            expected_insight_category="NO_MATERIAL_IMPACT",
            expected_relevance_level="LOW",
            expected_relationship_interpretation=(
                "CVS Health's retail footprint changes are publicly significant but internal evidence directly "
                "confirms no material impact on the banking relationship, which remains flat and stable."
            ),
            expected_action="REVIEW",
            explanation="A second neutral-relevance case (paired with McKesson) using a different kind of public event, to confirm the agent isn't just keying off 'leadership change' as a special case.",
        ),
    ),
    "COR": dict(
        relationship_strength="developing", relationship_status="stable",
        current_annual_revenue=40_000_000, prior_year_revenue=37_700_000,
        transaction_volume_ytd=310_000_000, relationship_start_date=date(2021, 10, 1),
        segments=[
            (12, 3.05, 3.2, 8.5, 9.2, 20, 19, "stable"),
            (12, 3.2, 3.33, 9.2, 10, 19, 18, "slow_growth"),
        ],
        products=[
            ("payments", 16_000_000, "active", "stable"),
            ("treasury_services", 14_000_000, "active", "stable"),
            ("fx", 10_000_000, "active", "growing"),
        ],
        flagship_opportunity=dict(
            name="Treasury services expansion", value=4_000_000, stage="prospecting",
            probability_pct=15, strategic_importance="low", status="active",
            competitive_pressure="none", competitor_name=None,
        ),
        extra_opportunities=[],
        flagship_interaction=dict(
            topic="product_discussion", sentiment="neutral",
            summary="Introductory call with a newly assigned treasury contact; relationship history and "
                     "recent public event were not discussed in depth.",
        ),
        flagship_note=(
            "This was only my second substantive conversation with Cencora's treasury function since the "
            "relationship began a few years ago, and it was with a contact who was new to the role. The "
            "relationship remains genuinely small and under-documented on our side -- we have limited "
            "interaction history, only a handful of logged notes, and no meaningful pipeline activity beyond "
            "one early-stage prospecting opportunity. I raised the recently announced public event to gauge "
            "reaction, but the contact was not able to speak to strategic implications and deferred to "
            "colleagues I have not yet met. Revenue has been modestly positive but the relationship is thin "
            "by any measure -- few products, few interactions, and now a contact transition. I do not have "
            "enough internal evidence from this relationship to draw a confident conclusion about how the "
            "public event connects to our banking relationship. Recommend scheduling a proper relationship "
            "mapping session before drawing further conclusions."
        ),
        risk_comment_recent="Risk low but relationship coverage is thin; limited interaction history constrains confidence in any risk trend assessment.",
        external_signal=dict(
            headline="Cencora announces significant corporate strategic initiative",
            description="Cencora announced a significant corporate strategic initiative intended to "
                         "reposition parts of its distribution business over the coming fiscal year.",
            character="significant_neutral",
        ),
        ground_truth=dict(
            expected_internal_signal="Small, thinly-documented relationship with very limited interaction and note history, and an explicit statement that the newest contact could not speak to the event",
            expected_signal_alignment="INSUFFICIENT",
            expected_insight_category="INSUFFICIENT_EVIDENCE",
            expected_relevance_level="LOW",
            expected_relationship_interpretation=(
                "The relationship with Cencora is too thinly documented to produce a confident, personalized "
                "conclusion about how this public event affects the bank's position -- the agent should "
                "recognize the evidence gap rather than speculate."
            ),
            expected_action="REVIEW",
            explanation="A second insufficient-evidence case (paired with Walmart) driven by genuinely sparse relationship data rather than a topic mismatch, to test both failure modes of 'not enough evidence.'",
        ),
    ),
}


PROFILE_BY_CODE = PROFILES
for c in COMPANIES:
    c["profile"] = PROFILE_BY_CODE[c["code"]]

# ---------------------------------------------------------------------------
# 3. Evidence-code allocation and small deterministic helpers
# ---------------------------------------------------------------------------


class EvidenceCounter:
    def __init__(self):
        self._n = {}

    def next(self, prefix):
        self._n[prefix] = self._n.get(prefix, 0) + 1
        return f"{prefix}_{self._n[prefix]:03d}"


def months_back(end_month, n):
    """observation_month values for the n months ending at end_month, oldest first."""
    months = []
    y, m = end_month.year, end_month.month
    for _ in range(n):
        months.append(date(y, m, 1))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return list(reversed(months))


def interpolate(start, end, n, rng, noise_pct=0.03):
    values = []
    for i in range(n):
        t = i / max(n - 1, 1)
        base = start + (end - start) * t
        noisy = base * (1 + rng.uniform(-noise_pct, noise_pct))
        values.append(round(noisy, 2))
    return values


def build_monthly_series(segments, rng):
    """segments: list of (n, rev_start, rev_end, pipe_start, pipe_end, risk_start, risk_end, label)."""
    revenue, pipeline, risk, labels = [], [], [], []
    for n, r0, r1, p0, p1, k0, k1, label in segments:
        revenue.extend(interpolate(r0 * 1_000_000, r1 * 1_000_000, n, rng))
        pipeline.extend(interpolate(p0 * 1_000_000, p1 * 1_000_000, n, rng))
        risk.extend(interpolate(k0, k1, n, rng, noise_pct=0.05))
        labels.extend([label] * n)
    return revenue, pipeline, risk, labels


SENTIMENT_BY_TREND = {
    "rapid_growth": ["positive", "positive", "neutral"],
    "slow_growth": ["positive", "neutral", "neutral"],
    "stable": ["neutral", "neutral", "positive"],
    "declining": ["negative", "neutral", "mixed"],
    "sudden_deterioration": ["negative", "negative", "mixed"],
    "recovering": ["positive", "neutral", "mixed"],
}

RISK_TREND_BY_LABEL = {
    "rapid_growth": "improving", "recovering": "improving",
    "slow_growth": "stable", "stable": "stable",
    "declining": "worsening", "sudden_deterioration": "worsening",
}

# ---------------------------------------------------------------------------
# 4. Filler content templates (bulk, non-scenario-critical rows)
# ---------------------------------------------------------------------------

FILLER_INTERACTION_TEMPLATES = {
    "expansion_plans": "{rm} discussed {company}'s expansion plans and how upcoming banking needs might evolve.",
    "investment_priorities": "Reviewed {company}'s current investment priorities and how our product set aligns with them.",
    "relationship_concerns": "{rm} checked in on general relationship health and surfaced no new concerns beyond prior discussions.",
    "product_discussion": "Walked {company}'s finance team through recent enhancements to our {product} offering.",
    "competitor_activity": "{company} mentioned general market activity from competing banks without specifics.",
    "renewal_discussion": "Routine check-in ahead of an upcoming renewal cycle for {company}'s {product} services.",
    "strategic_opportunity": "Explored a potential strategic opportunity with {company}'s corporate development team.",
}

FILLER_NOTE_SENTENCES = [
    "Met with {company}'s finance team for a regular relationship check-in covering current account activity.",
    "{rm} reviewed recent transaction volumes across the account and confirmed nothing unusual to report.",
    "The conversation touched briefly on {product} usage, which remains consistent with prior quarters.",
    "No new competitive activity or concerns were raised by the client during this conversation.",
    "The team confirmed their point of contact structure remains unchanged since our last interaction.",
    "We discussed general market conditions in the {industry} sector without specific implications for the account.",
    "{rm} noted that the executive sponsor relationship remains healthy and responsive.",
    "Follow-up items from this conversation are limited to routine documentation updates.",
    "The client did not raise any pending decisions that would require escalation on our side.",
    "Overall tone of the conversation was professional and consistent with the account's established cadence.",
    "We confirmed the next scheduled touchpoint and agreed on standard follow-up cadence.",
    "{rm} flagged no changes to the account's risk profile based on this conversation.",
]


def make_filler_interaction(company, topic, sentiment, rm, rng):
    product = rng.choice(company["profile"]["products"])[0]
    text = FILLER_INTERACTION_TEMPLATES[topic].format(company=company["name"], rm=rm, product=product)
    return topic, sentiment, text


def make_filler_note(company, rm, rng, target_words=180):
    pool = FILLER_NOTE_SENTENCES[:]
    rng.shuffle(pool)
    product = rng.choice(company["profile"]["products"])[0]
    sentences = []
    word_count = 0
    for template in pool:
        sentence = template.format(company=company["name"], rm=rm, product=product, industry=company["industry"])
        sentences.append(sentence)
        word_count += len(sentence.split())
        if word_count >= target_words:
            break
    return " ".join(sentences)


# ---------------------------------------------------------------------------
# 5. SQL emission helpers
# ---------------------------------------------------------------------------


def sql_value(v):
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, date):
        return f"'{v.isoformat()}'"
    if isinstance(v, (list, tuple)):
        inner = ", ".join(sql_value(x) for x in v)
        return f"ARRAY[{inner}]::text[]"
    text = str(v).replace("'", "''")
    return f"'{text}'"


def insert_statement(table, columns, rows):
    if not rows:
        return ""
    col_list = ", ".join(columns)
    lines = []
    for row in rows:
        values = ", ".join(sql_value(row[c]) for c in columns)
        lines.append(f"  ({values})")
    return f"insert into public.{table} ({col_list}) values\n" + ",\n".join(lines) + ";\n"


# ---------------------------------------------------------------------------
# 6. Row builders
# ---------------------------------------------------------------------------


def generate():
    ev = EvidenceCounter()
    tables = {
        "company_master": [], "relationship_snapshot": [], "relationship_metrics_monthly": [],
        "products": [], "opportunities": [], "risk_assessment": [], "client_interactions": [],
        "internal_notes": [], "external_signals": [], "insight_ground_truth": [],
    }

    for idx, company in enumerate(COMPANIES):
        rng = random.Random(SEED + 100 + idx)
        profile = company["profile"]
        company_code = f"CLI_{idx + 1:03d}"

        tables["company_master"].append({
            "company_code": company_code, "company_name": company["name"], "ticker": company["ticker"],
            "cik": None, "industry": company["industry"], "sector": company["sector"],
            "fortune500_flag": True, "fortune_rank": None, "relationship_tier": company["tier"],
            "relationship_start_date": profile["relationship_start_date"], "synthetic_flag": True,
        })

        rm = RM_NAMES[idx]
        exec_sponsor = EXEC_SPONSOR_NAMES[idx]
        yoy_growth = round(
            (profile["current_annual_revenue"] - profile["prior_year_revenue"])
            / profile["prior_year_revenue"] * 100, 2,
        )
        rel_code = ev.next("REL")
        tables["relationship_snapshot"].append({
            "evidence_code": rel_code, "company_code": company_code,
            "relationship_strength": profile["relationship_strength"],
            "current_annual_revenue": profile["current_annual_revenue"],
            "prior_year_revenue": profile["prior_year_revenue"],
            "yoy_growth_pct": yoy_growth,
            "transaction_volume_ytd": profile["transaction_volume_ytd"],
            "relationship_status": profile["relationship_status"],
            "relationship_manager": rm, "executive_sponsor": exec_sponsor,
            "as_of_date": END_MONTH,
        })

        # -- monthly time series --
        months = months_back(END_MONTH, 24)
        revenue, pipeline, risk, labels = build_monthly_series(profile["segments"], rng)
        txn_multiplier = rng.uniform(16, 24)
        last_relm_code = None
        for month, rev, pipe, risk_score, label in zip(months, revenue, pipeline, risk, labels):
            code = ev.next("RELM")
            last_relm_code = code
            sentiment = rng.choice(SENTIMENT_BY_TREND[label])
            tables["relationship_metrics_monthly"].append({
                "evidence_code": code, "company_code": company_code, "observation_month": month,
                "transaction_volume": round(rev * txn_multiplier * rng.uniform(0.9, 1.1), 2),
                "relationship_revenue": rev, "pipeline_value": pipe, "risk_score": round(risk_score, 2),
                "sentiment_label": sentiment, "trend_label": label,
            })

        # -- products --
        product_codes = []
        for name, revenue_amt, status, growth_trend in profile["products"]:
            code = ev.next("PROD")
            product_codes.append(code)
            renewal_offset = rng.randint(30, 540)
            tables["products"].append({
                "evidence_code": code, "company_code": company_code, "product_name": name,
                "annual_revenue": revenue_amt, "product_status": status, "growth_trend": growth_trend,
                "renewal_date": END_MONTH + timedelta(days=renewal_offset),
            })

        # -- opportunities (flagship first) --
        fo = profile["flagship_opportunity"]
        flagship_close_offset = rng.randint(20, 90)
        flagship_opp_code = ev.next("OPP")
        tables["opportunities"].append({
            "evidence_code": flagship_opp_code, "company_code": company_code,
            "opportunity_name": fo["name"], "opportunity_value": fo["value"], "stage": fo["stage"],
            "probability_pct": fo["probability_pct"],
            "expected_close_date": END_MONTH + timedelta(days=flagship_close_offset),
            "strategic_importance": fo["strategic_importance"], "status": fo["status"],
            "competitive_pressure": fo["competitive_pressure"], "competitor_name": fo["competitor_name"],
        })
        for name, value, stage, prob, importance, status, pressure, competitor in profile["extra_opportunities"]:
            code = ev.next("OPP")
            close_offset = rng.randint(20, 180)
            tables["opportunities"].append({
                "evidence_code": code, "company_code": company_code, "opportunity_name": name,
                "opportunity_value": value, "stage": stage, "probability_pct": prob,
                "expected_close_date": END_MONTH + timedelta(days=close_offset),
                "strategic_importance": importance, "status": status,
                "competitive_pressure": pressure, "competitor_name": competitor,
            })

        # -- risk assessment, quarterly (8 quarters over 24 months) --
        flagship_risk_code = None
        for q in range(8):
            month_index = q * 3 + 2
            as_of = months[month_index]
            risk_score = risk[month_index]
            label = labels[month_index]
            trend = RISK_TREND_BY_LABEL[label]
            code = ev.next("RISK")
            if q == 7:
                flagship_risk_code = code
                comment = profile["risk_comment_recent"]
            else:
                comment = (
                    f"Quarterly review: relationship risk trending {trend} based on revenue and pipeline "
                    f"movement observed during the period."
                )
            credit_exposure = round(profile["current_annual_revenue"] * rng.uniform(0.15, 0.35), 2)
            tables["risk_assessment"].append({
                "evidence_code": code, "company_code": company_code, "as_of_date": as_of,
                "credit_exposure": credit_exposure,
                "relationship_risk_score": round(risk_score, 2),
                "concentration_risk_score": round(min(100, max(0, risk_score + rng.uniform(-8, 8))), 2),
                "operational_risk_score": round(min(100, max(0, risk_score * 0.6 + rng.uniform(-5, 5))), 2),
                "risk_trend": trend, "explanatory_comment": comment,
            })

        # -- client interactions (flagship most recent + filler) --
        n_interactions = 10 if company["tier"] == "tier_1" else 7
        fi = profile["flagship_interaction"]
        flagship_int_code = ev.next("INT")
        tables["client_interactions"].append({
            "evidence_code": flagship_int_code, "company_code": company_code,
            "interaction_date": END_MONTH - timedelta(days=rng.randint(3, 14)),
            "interaction_type": rng.choice(["meeting", "call"]),
            "topic": fi["topic"], "attendees": [rm, exec_sponsor],
            "summary": fi["summary"], "sentiment": fi["sentiment"],
        })
        topics = list(FILLER_INTERACTION_TEMPLATES.keys())
        for i in range(n_interactions - 1):
            topic = rng.choice(topics)
            month_label = labels[min(23, i * 2)]
            sentiment = rng.choice(SENTIMENT_BY_TREND[month_label])
            _, sentiment, summary = make_filler_interaction(company, topic, sentiment, rm, rng)
            code = ev.next("INT")
            tables["client_interactions"].append({
                "evidence_code": code, "company_code": company_code,
                "interaction_date": END_MONTH - timedelta(days=rng.randint(15, 720)),
                "interaction_type": rng.choice(["meeting", "call", "email", "conference"]),
                "topic": topic, "attendees": [rm], "summary": summary, "sentiment": sentiment,
            })

        # -- internal notes (flagship, tied to flagship interaction, + filler) --
        n_notes = 6 if company["tier"] == "tier_1" else 4
        flagship_note_code = ev.next("NOTE")
        tables["internal_notes"].append({
            "evidence_code": flagship_note_code, "company_code": company_code,
            "related_interaction_evidence_code": flagship_int_code,
            "note_date": END_MONTH - timedelta(days=rng.randint(3, 14)),
            "author": rm, "note_text": profile["flagship_note"],
            "tags": [company["scenario"].lower(), "flagship"],
        })
        for i in range(n_notes - 1):
            code = ev.next("NOTE")
            tables["internal_notes"].append({
                "evidence_code": code, "company_code": company_code,
                "related_interaction_evidence_code": None,
                "note_date": END_MONTH - timedelta(days=rng.randint(20, 700)),
                "author": rng.choice(RM_NAMES), "note_text": make_filler_note(company, rm, rng),
                "tags": ["routine"],
            })

        # -- external signal --
        es = profile["external_signal"]
        signal_code = ev.next("SIG")
        tables["external_signals"].append({
            "evidence_code": signal_code, "company_code": company_code,
            "signal_date": END_MONTH - timedelta(days=rng.randint(5, 20)),
            "headline": es["headline"], "description": es["description"],
            "signal_character": es["character"], "synthetic_flag": True,
        })

        # -- ground truth --
        gt = profile["ground_truth"]
        gt_code = ev.next("GT")
        key_evidence = [rel_code, flagship_opp_code, flagship_note_code, flagship_int_code,
                         flagship_risk_code, last_relm_code]
        tables["insight_ground_truth"].append({
            "evidence_code": gt_code, "company_code": company_code, "external_signal_evidence_code": signal_code,
            "expected_internal_signal": gt["expected_internal_signal"],
            "expected_signal_alignment": gt["expected_signal_alignment"],
            "expected_insight_category": gt["expected_insight_category"],
            "expected_relevance_level": gt["expected_relevance_level"],
            "expected_relationship_interpretation": gt["expected_relationship_interpretation"],
            "key_internal_evidence_ids": key_evidence,
            "expected_action": gt["expected_action"], "explanation": gt["explanation"],
        })

    return tables


# ---------------------------------------------------------------------------
# 7. SQL file emission (resolves company_code / evidence_code lookups to FKs)
# ---------------------------------------------------------------------------


def render_sql(tables):
    out = ["begin;\n"]

    out.append(insert_statement(
        "company_master",
        ["company_code", "company_name", "ticker", "cik", "industry", "sector",
         "fortune500_flag", "fortune_rank", "relationship_tier", "relationship_start_date", "synthetic_flag"],
        tables["company_master"],
    ))

    def with_company_fk(rows):
        return [dict(r, company_id=f"(select company_id from public.company_master where company_code = '{r['company_code']}')") for r in rows]

    # relationship_snapshot
    rows = with_company_fk(tables["relationship_snapshot"])
    out.append(_insert_with_subquery(
        "relationship_snapshot",
        ["evidence_code", "company_id", "relationship_strength", "current_annual_revenue",
         "prior_year_revenue", "yoy_growth_pct", "transaction_volume_ytd", "relationship_status",
         "relationship_manager", "executive_sponsor", "as_of_date"],
        rows,
    ))

    rows = with_company_fk(tables["relationship_metrics_monthly"])
    out.append(_insert_with_subquery(
        "relationship_metrics_monthly",
        ["evidence_code", "company_id", "observation_month", "transaction_volume",
         "relationship_revenue", "pipeline_value", "risk_score", "sentiment_label", "trend_label"],
        rows,
    ))

    rows = with_company_fk(tables["products"])
    out.append(_insert_with_subquery(
        "products",
        ["evidence_code", "company_id", "product_name", "annual_revenue", "product_status",
         "growth_trend", "renewal_date"],
        rows,
    ))

    rows = with_company_fk(tables["opportunities"])
    out.append(_insert_with_subquery(
        "opportunities",
        ["evidence_code", "company_id", "opportunity_name", "opportunity_value", "stage",
         "probability_pct", "expected_close_date", "strategic_importance", "status",
         "competitive_pressure", "competitor_name"],
        rows,
    ))

    rows = with_company_fk(tables["risk_assessment"])
    out.append(_insert_with_subquery(
        "risk_assessment",
        ["evidence_code", "company_id", "as_of_date", "credit_exposure", "relationship_risk_score",
         "concentration_risk_score", "operational_risk_score", "risk_trend", "explanatory_comment"],
        rows,
    ))

    rows = with_company_fk(tables["client_interactions"])
    out.append(_insert_with_subquery(
        "client_interactions",
        ["evidence_code", "company_id", "interaction_date", "interaction_type", "topic",
         "attendees", "summary", "sentiment"],
        rows,
    ))

    rows = with_company_fk(tables["internal_notes"])
    out.append(_insert_notes(rows))

    rows = with_company_fk(tables["external_signals"])
    out.append(_insert_with_subquery(
        "external_signals",
        ["evidence_code", "company_id", "signal_date", "headline", "description",
         "signal_character", "synthetic_flag"],
        rows,
    ))

    rows = with_company_fk(tables["insight_ground_truth"])
    out.append(_insert_ground_truth(rows))

    out.append("commit;\n")
    return "\n".join(out)


def _insert_with_subquery(table, columns, rows):
    if not rows:
        return ""
    col_list = ", ".join(columns)
    lines = []
    for row in rows:
        values = []
        for c in columns:
            if c == "company_id":
                values.append(row["company_id"])
            else:
                values.append(sql_value(row[c]))
        lines.append(f"  ({', '.join(values)})")
    return f"insert into public.{table} ({col_list}) values\n" + ",\n".join(lines) + ";\n"


def _insert_notes(rows):
    columns = ["evidence_code", "company_id", "related_interaction_id", "note_date", "author", "note_text", "tags"]
    lines = []
    for row in rows:
        related = row["related_interaction_evidence_code"]
        related_sql = (
            f"(select interaction_id from public.client_interactions where evidence_code = '{related}')"
            if related else "NULL"
        )
        values = [
            sql_value(row["evidence_code"]), row["company_id"], related_sql,
            sql_value(row["note_date"]), sql_value(row["author"]), sql_value(row["note_text"]),
            sql_value(row["tags"]),
        ]
        lines.append(f"  ({', '.join(values)})")
    col_list = ", ".join(columns)
    return f"insert into public.internal_notes ({col_list}) values\n" + ",\n".join(lines) + ";\n"


def _insert_ground_truth(rows):
    columns = ["evidence_code", "company_id", "external_signal_id", "expected_internal_signal",
               "expected_signal_alignment", "expected_insight_category", "expected_relevance_level",
               "expected_relationship_interpretation", "key_internal_evidence_ids", "expected_action",
               "explanation"]
    lines = []
    for row in rows:
        signal_sub = (
            f"(select signal_id from public.external_signals where evidence_code = "
            f"'{row['external_signal_evidence_code']}')"
        )
        values = [
            sql_value(row["evidence_code"]), row["company_id"], signal_sub,
            sql_value(row["expected_internal_signal"]), sql_value(row["expected_signal_alignment"]),
            sql_value(row["expected_insight_category"]), sql_value(row["expected_relevance_level"]),
            sql_value(row["expected_relationship_interpretation"]), sql_value(row["key_internal_evidence_ids"]),
            sql_value(row["expected_action"]), sql_value(row["explanation"]),
        ]
        lines.append(f"  ({', '.join(values)})")
    col_list = ", ".join(columns)
    return f"insert into public.insight_ground_truth ({col_list}) values\n" + ",\n".join(lines) + ";\n"


def main():
    tables = generate()
    sql = render_sql(tables)
    OUTPUT_PATH.write_text(sql)
    print(f"Wrote {OUTPUT_PATH}")
    for name, rows in tables.items():
        print(f"  {name}: {len(rows)} rows")
    print("\nTier 1:", [c["name"] for c in COMPANIES if c["tier"] == "tier_1"])
    print("Tier 2:", [c["name"] for c in COMPANIES if c["tier"] == "tier_2"])
    for c in COMPANIES:
        print(f"  {c['name']:22s} {c['tier']}  {c['scenario']}")


if __name__ == "__main__":
    main()
