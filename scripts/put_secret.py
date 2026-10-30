"""Store one secret in SSM Parameter Store as a SecureString. Called by put-secrets.sh.

    python scripts/put_secret.py /navi/prod/discord_token

The value is read with a hidden prompt (getpass) and sent to AWS by boto3: it never appears in arguments, the process list, a file or shell history.
Blank input skips. Uses AWS_PROFILE / AWS_DEFAULT_REGION from the environment.
"""
from __future__ import annotations

import getpass
import sys


def put_secret(name: str, value: str, client=None) -> bool:
    if not value:
        return False
    if client is None:
        import boto3

        client = boto3.client("ssm")
    client.put_parameter(Name=name, Type="SecureString", Value=value, Overwrite=True)
    return True


def main(argv: list[str]) -> int:
    if len(argv) != 1 or not argv[0].startswith("/"):
        print("usage: put_secret.py /navi/<env>/<name>", file=sys.stderr)
        return 2
    value = getpass.getpass(f"Value for {argv[0]} (blank = skip): ")
    print(f"  saved {argv[0]}" if put_secret(argv[0], value) else f"  skipped {argv[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
