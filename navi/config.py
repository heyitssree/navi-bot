# navi/config.py - environment configuration (and optional SSM Parameter Store loading)

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger("navi.config")


# Parameters under the prefix that belong to the infrastructure, not to the app's configuration.
SSM_INFRA_KEYS = {"IMAGE_URI", "RUN_ENABLED", "BUCKET"}


def load_ssm_parameters(prefix: str, client=None) -> int:
    """Copy SSM parameters under *prefix* into os.environ (existing variables win). Returns how many were set.

    Used when NAVI_SSM_PREFIX is set (e.g. "/navi/prod/"). The parameter name after the prefix becomes the
    variable name, so /navi/prod/discord_token -> DISCORD_TOKEN (names are upper-cased). SecureString values are decrypted.
    """
    if client is None:
        import boto3  # only needed on AWS

        client = boto3.client("ssm")
    prefix = prefix if prefix.endswith("/") else prefix + "/"
    count = 0
    token = None
    while True:
        kwargs = {"Path": prefix, "WithDecryption": True, "Recursive": False}
        if token:
            kwargs["NextToken"] = token
        resp = client.get_parameters_by_path(**kwargs)
        for param in resp.get("Parameters", []):
            key = param["Name"][len(prefix):].upper()          # /navi/prod/discord_token -> DISCORD_TOKEN
            if key and key not in SSM_INFRA_KEYS and key not in os.environ:
                os.environ[key] = param["Value"]
                count += 1
        token = resp.get("NextToken")
        if not token:
            break
    logger.info("Loaded %d parameters from SSM prefix %s", count, prefix)
    return count


@dataclass(frozen=True)
class Config:
    discord_token: str | None
    free_api_key: str | None
    paid_api_key: str | None
    llm_model: str | None
    free_tier_mode: bool
    general_channel: str
    mod_channel_name: str
    owner_id: int | None   # Set OWNER_ID in .env so no other user can ever invoke /admin commands.
    guild_id: int | None
    partner_port: int
    bedrock_model_id: str | None = None   # BEDROCK_MODEL_ID: global inference profile id
    aws_region: str = "ap-south-1"
    bucket: str | None = None            # NAVI_BUCKET: private S3 bucket (media, exports, Litestream)
    privacy_db_path: str | None = None   # default: privacy.db next to the main database

    @classmethod
    def from_env(cls) -> "Config":
        from dotenv import load_dotenv

        load_dotenv()
        prefix = os.getenv("NAVI_SSM_PREFIX")
        if prefix:
            load_ssm_parameters(prefix)
        raw_owner = os.getenv("OWNER_ID", "")
        return cls(
            discord_token=os.getenv("DISCORD_TOKEN"),
            free_api_key=os.getenv("GEMINI_API_KEY_FREE"),
            # Support old single-key env var as alias for paid key
            paid_api_key=os.getenv("GEMINI_API_KEY_PAID") or os.getenv("GEMINI_API_KEY"),
            llm_model=os.getenv("LLM_MODEL"),
            free_tier_mode=os.getenv("FREE_TIER_MODE", "true").lower() == "true",
            general_channel=os.getenv("GENERAL_CHANNEL", "general"),
            mod_channel_name=os.getenv("MOD_CHANNEL_NAME", "mod-log"),
            owner_id=int(raw_owner) if raw_owner.isdigit() else None,
            guild_id=int(os.getenv("GUILD_ID", "0")) or None,
            partner_port=int(os.getenv("API_SERVER_PORT", "8080")),
            bedrock_model_id=os.getenv("BEDROCK_MODEL_ID") or None,
            aws_region=os.getenv("AWS_REGION", "ap-south-1"),
            bucket=os.getenv("NAVI_BUCKET") or None,
            privacy_db_path=os.getenv("PRIVACY_DB_PATH"),
        )
