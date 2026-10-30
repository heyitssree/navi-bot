# navi/llm/bedrock.py - Amazon Bedrock provider (Converse API). Works with an on-demand model (e.g. google.gemma-3-12b-it) or a
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
PROFILE_PREFIXES = {"global", "apac", "in", "us", "eu", "jp", "au", "ca", "us-gov"}
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
                             "(a model id such as google.gemma-3-12b-it, or an inference profile id from `aws bedrock list-inference-profiles`).")
        self.model = model_id                  # an on-demand model id or a cross-Region inference profile id
        self._system_supported = True          # flips to False if the model rejects Converse system prompts
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

    def _converse(self, req: LLMRequest) -> dict:
        kwargs = dict(modelId=self.model, inferenceConfig={"maxTokens": req.max_tokens, "temperature": req.temperature})
        if self._system_supported:
            try:
                return self._client.converse(system=[{"text": req.system}],
                                             messages=[{"role": "user", "content": [{"text": req.prompt}]}], **kwargs)
            except Exception as exc:
                code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
                if code != "ValidationException" or "system" not in str(exc).lower():
                    raise
                self._system_supported = False       # some models (e.g. Gemma) take no system prompt: fold it into the message
                logger.warning("Model %s rejects system prompts; sending the instructions inside the user message.", self.model)
        text = f"{req.system}\n\n{req.prompt}" if req.system else req.prompt
        return self._client.converse(messages=[{"role": "user", "content": [{"text": text}]}], **kwargs)

    async def generate(self, req: LLMRequest, key: str | None = None) -> LLMResponse:
        t0 = time.monotonic()
        try:
            resp = await asyncio.to_thread(self._converse, req)
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

        A missing permission is only a warning: invoking the model is what really matters. A plain on-demand model id
        (no geography prefix) has no profile to check.
        """
        if self.model.split(".", 1)[0] not in PROFILE_PREFIXES:
            logger.info("Active Bedrock model: %s (on-demand)", self.model)
            return self.model, None
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
