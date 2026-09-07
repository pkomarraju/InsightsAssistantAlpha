"""Shared LLM configuration and process-wide request pacing."""

import os

from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain_openai import ChatOpenAI


MODEL = os.environ.get("INSIGHTS_MODEL") or "gpt-4o"
MODEL_MAX_OUTPUT_TOKENS = int(os.environ.get("INSIGHTS_MODEL_MAX_OUTPUT_TOKENS") or 1_500)
LLM_MIN_INTERVAL_SECONDS = float(os.environ.get("INSIGHTS_LLM_MIN_INTERVAL_SECONDS") or 20)

# One limiter is deliberately shared by every agent and synthesis model in
# this process. At the prototype's 30K TPM tier, spacing calls is more useful
# than allowing each agent to independently exhaust the rolling window.
LLM_RATE_LIMITER = InMemoryRateLimiter(
    requests_per_second=1 / LLM_MIN_INTERVAL_SECONDS,
    check_every_n_seconds=min(0.5, LLM_MIN_INTERVAL_SECONDS),
    max_bucket_size=1,
)


def chat_model() -> ChatOpenAI:
    return ChatOpenAI(
        model=MODEL,
        temperature=0,
        max_tokens=MODEL_MAX_OUTPUT_TOKENS,
        rate_limiter=LLM_RATE_LIMITER,
    )
