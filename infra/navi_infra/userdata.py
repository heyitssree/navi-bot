"""Render the instance bootstrap script from navi_infra/assets/ (update.sh and navi.service are embedded)."""
from __future__ import annotations

from pathlib import Path

ASSETS = Path(__file__).resolve().parent / "assets"


def render_user_data(*, env_name: str, region: str, bucket: str, log_group: str, image_param: str,
                     bedrock_model_id: str) -> list[str]:
    """Return the user-data script as a list of lines. Values may be CDK tokens (resolved at deploy time)."""
    text = (ASSETS / "user_data.sh").read_text()
    text = text.split("\n", 1)[1] if text.startswith("#!") else text     # ec2.UserData.for_linux adds its own shebang
    text = text.replace("__UPDATE_SH__", (ASSETS / "update.sh").read_text().rstrip("\n"))
    text = text.replace("__NAVI_SERVICE__", (ASSETS / "navi.service").read_text().rstrip("\n"))
    for key, value in {
        "__REGION__": region, "__ENV__": env_name, "__BUCKET__": bucket, "__LOG_GROUP__": log_group,
        "__IMAGE_PARAM__": image_param, "__BEDROCK_MODEL_ID__": bedrock_model_id,
    }.items():
        text = text.replace(key, value)
    return text.splitlines()
