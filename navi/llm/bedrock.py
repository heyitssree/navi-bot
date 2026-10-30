# navi/llm/bedrock.py - Amazon Bedrock provider (Converse API). Used for Claude Haiku 5.5 behind a global
# cross-Region inference profile; the model id comes from ai.bedrock_model_id / BEDROCK_MODEL_ID, never hardcoded.

from __future__ import annotations

import asyncio
import logging
import time

from navi.llm.base import LLMError, LLMRequest, LLMResponse

logger = logging.getLogger("navi.llm.bedrock")

THROTTLE = {"ThrottlingException", "TooManyRequestsException", "ServiceQuotaExceededException"}
CONFIG = {"AccessDeniedException", "ValidationException", "ResourceNotFoundException", "UnrecognizedClientException",
          "ExpiredTokenException", "InvalidSignatureException", "UnauthorizedException"}
DEFAULT_REGION = "ap-south-1"
THROTTLE_RETRY_AFTER = 10.0


def classify_client_error(exc: Exception) -> LLMError:
    """Map a botocore ClientError (or connection error) onto rate_limited / config / server."""
    from botocore.exceptions import ClientError

    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code", "")
        kind = "rate_limited" if code in THROTTLE else "config" if code in CONFIG else "server"
        return LLMError(kind, f"{code}: {exc}", retry_after=THROTTLE_RETRY_AFTER if kind == "rate_limited" else None)
    return LLMError("server", f"{type(exc).__name__}: {exc}")


class BedrockProvider:
    name = "bedrock"
    key_names = [""]            # one credential chain (instance role, or the local AWS profile)
    paid_keys = frozenset()

    def __init__(self, model_id: str, region: str = DEFAULT_REGION, *, client=None, control_client=None) -> None:
        if not model_id:
            raise ValueError("Bedrock needs a model id: set ai.bedrock_model_id or BEDROCK_MODEL_ID "
                             "(a global inference profile id; list them with `aws bedrock list-inference-profiles`).")
        self.model = model_id                  # the global cross-Region inference profile id
        self.region = region
        if client is None:
            import boto3
            from botocore.config import Config

            client = boto3.client(
                "bedrock-runtime", region_name=region,
                config=Config(retries={"max_attempts": 2, "mode": "standard"}, connect_timeout=5, read_timeout=30))
        self._client = client
        self._control = control_client
        logger.info("BedrockProvider initialised. Model: %s, region: %s", model_id, region)

    async def generate(self, req: LLMRequest, key: str | None = None) -> LLMResponse:
        t0 = time.monotonic()
        try:
            resp = await asyncio.to_thread(
                self._client.converse,
                modelId=self.model,
                system=[{"text": req.system}],
                messages=[{"role": "user", "content": [{"text": req.prompt}]}],
                inferenceConfig={"maxTokens": req.max_tokens, "temperature": req.temperature},
            )
        except Exception as exc:
            raise classify_client_error(exc) from exc
        blocks = resp["output"]["message"]["content"]
        usage = resp.get("usage", {})
        return LLMResponse(
            text="".join(b.get("text", "") for b in blocks).strip(),
            input_tokens=usage.get("inputTokens", 0),
            output_tokens=usage.get("outputTokens", 0),
            provider=self.name,
            model=self.model,
            latency_ms=int((time.monotonic() - t0) * 1000),
        )

    def verify_model_sync(self) -> tuple[str, LLMError | None]:
        """Startup check: the inference profile exists and is ACTIVE (needs bedrock:GetInferenceProfile).

        A missing permission is only a warning: invoking the model is what really matters.
        """
        try:
            if self._control is None:
                import boto3

                self._control = boto3.client("bedrock", region_name=self.region)
            profile = self._control.get_inference_profile(inferenceProfileIdentifier=self.model)
        except Exception as exc:
            err = classify_client_error(exc)
            code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
            if code in ("ResourceNotFoundException", "ValidationException"):
                logger.error("Bedrock inference profile %r not found in %s.", self.model, self.region)
                return self.model, err
            logger.warning("Could not check the Bedrock inference profile (%s); continuing.", err)
            return self.model, LLMError("server", str(err))      # non-config: logged by the router, never alarming
        status = profile.get("status", "ACTIVE")
        if status != "ACTIVE":
            return self.model, LLMError("config", f"inference profile {self.model} is {status}")
        logger.info("Active Bedrock model: %s (%s)", self.model, profile.get("inferenceProfileName", ""))
        return self.model, None
