#!/usr/bin/env python3
"""Admin one-off: map a Cognito subject to an internal user_id.

Pre-Cognito data lives under an opaque internal id (u_001). After creating a
Cognito user, link its `sub` so the same memory state is served:

    python scripts/link_user.py <cognito-sub> u_001 [--table language-memory]

Find the sub with:
    aws cognito-idp admin-get-user --user-pool-id <pool> --username <email> \
        --query "UserAttributes[?Name=='sub'].Value" --output text
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from yomu.repository import Repository  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("external_id", help="Cognito sub (UUID)")
    parser.add_argument("user_id", help="internal user id, e.g. u_001")
    parser.add_argument("--table", default="language-memory")
    args = parser.parse_args()

    repo = Repository(args.table)
    existing = repo.get_user_mapping(args.external_id)
    if existing and existing != args.user_id:
        sys.exit(f"refusing: {args.external_id} already maps to {existing}")
    repo.put_user_mapping(args.external_id, args.user_id)
    print(f"{args.external_id} → {args.user_id}")


if __name__ == "__main__":
    main()
