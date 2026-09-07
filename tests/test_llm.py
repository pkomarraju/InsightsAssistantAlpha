from insights_assistant import llm


def test_all_chat_models_share_process_rate_limiter():
    first = llm.chat_model()
    second = llm.chat_model()

    assert first.rate_limiter is llm.LLM_RATE_LIMITER
    assert second.rate_limiter is llm.LLM_RATE_LIMITER
    assert first.max_tokens == 1_500
