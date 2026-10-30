# navi/llm/factory.py - which providers this process can use (credentials / model id present)

from __future__ import annotations

from navi.config import Config


def build_providers(config: Config, settings=None) -> list:
    """Gemini when an API key is set, Bedrock when a model id is set (ai.bedrock_model_id wins over BEDROCK_MODEL_ID).

    The first provider is the router's primary; ai.provider chooses which one answers.
    """
    providers = []
    if config.free_api_key or config.paid_api_key:
        from navi.llm.gemini import GeminiProvider

        providers.append(GeminiProvider(config.free_api_key, config.paid_api_key, config.llm_model))
    model_id = (settings.get("ai.bedrock_model_id") if settings is not None else "") or config.bedrock_model_id
    if model_id:
        from navi.llm.bedrock import BedrockProvider

        providers.append(BedrockProvider(model_id, config.aws_region))
    if not providers:
        raise ValueError("No LLM provider is configured (Gemini API key or BEDROCK_MODEL_ID).")
    return providers
