# navi/services/heartbeat.py - publish a Navi/Heartbeat metric every 5 minutes (only when NAVI_ENV is set, i.e. on AWS).
# The CloudWatch alarm in infra/ pages the owner when 3 consecutive 5-minute periods have no sample.

from __future__ import annotations

import asyncio
import logging
import os

logger = logging.getLogger("navi.services.heartbeat")

NAMESPACE = "Navi"
METRIC = "Heartbeat"
INTERVAL_SECONDS = 300

_client = None


def _cloudwatch():
    global _client
    if _client is None:
        import boto3

        _client = boto3.client("cloudwatch")
    return _client


def put_heartbeat(env_name: str, client=None) -> None:
    (client or _cloudwatch()).put_metric_data(
        Namespace=NAMESPACE,
        MetricData=[{"MetricName": METRIC, "Dimensions": [{"Name": "Env", "Value": env_name}], "Value": 1.0, "Unit": "Count"}],
    )


async def heartbeat_loop(env_name: str | None = None, *, client=None, interval: float = INTERVAL_SECONDS) -> None:
    env_name = env_name or os.getenv("NAVI_ENV")
    if not env_name:
        return
    while True:
        try:
            await asyncio.get_running_loop().run_in_executor(None, put_heartbeat, env_name, client)
        except Exception as exc:                  # a metrics hiccup must never take the bot down
            logger.warning("Heartbeat failed: %s", exc)
        await asyncio.sleep(interval)
