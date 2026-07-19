#!/usr/bin/env python3
"""Fully local dev environment: in-memory DynamoDB (moto) + the MCP server.

Starts a moto server thread, creates the language-memory table, seeds a slice
of the N5 list, and serves the MCP app with bearer auth — no AWS account or
credentials involved.

Usage:
    python scripts/dev_server.py                 # localhost:8000/mcp, token "dev", 30 words
    python scripts/dev_server.py --seed 0        # empty table
    python scripts/dev_server.py --seed 717      # the full N5 list

Then connect with the MCP Inspector (npx @modelcontextprotocol/inspector),
transport "Streamable HTTP", URL http://localhost:8000/mcp, header
"Authorization: Bearer dev".
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--moto-port", type=int, default=8001)
    parser.add_argument("--token", default="dev")
    parser.add_argument("--table", default="language-memory")
    parser.add_argument("--user", default="u_001")
    parser.add_argument("--seed", type=int, default=30, metavar="N",
                        help="seed the first N N5 words (0 to skip; default 30)")
    args = parser.parse_args()

    # Everything below reads configuration from the environment, same as Lambda.
    os.environ["TABLE_NAME"] = args.table
    os.environ["AUTH_TOKEN"] = args.token
    os.environ["USER_ID"] = args.user
    os.environ["DYNAMODB_ENDPOINT"] = f"http://127.0.0.1:{args.moto_port}"
    # moto accepts any credentials; just make sure boto3 finds some.
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "local")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "local")
    os.environ.setdefault("AWS_DEFAULT_REGION", "eu-west-1")

    from moto.server import ThreadedMotoServer

    moto = ThreadedMotoServer(port=args.moto_port, verbose=False)
    moto.start()
    print(f"moto DynamoDB at {os.environ['DYNAMODB_ENDPOINT']} (in-memory, data lost on exit)")

    import boto3

    from yomu.table_schema import create_table

    dynamodb = boto3.resource("dynamodb", endpoint_url=os.environ["DYNAMODB_ENDPOINT"])
    create_table(dynamodb, args.table)
    print(f"table {args.table} created")

    if args.seed:
        from seed_n5 import build_concepts, seed

        seed(args.table, args.user, "ja", build_concepts(limit=args.seed))

    import uvicorn

    from yomu.server import build_app

    print(f"\nMCP endpoint:  http://localhost:{args.port}/mcp")
    print(f"Bearer token:  {args.token}\n")
    uvicorn.run(build_app(), host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
