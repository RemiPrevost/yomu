#!/usr/bin/env bash
# Build the Lambda deployment asset into dist/lambda.
# Run before `cdk deploy`. Targets the arm64 Python 3.13 Lambda runtime;
# boto3 is provided by the runtime and deliberately not bundled.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/dist/lambda"

rm -rf "$OUT"
mkdir -p "$OUT"

"$ROOT/.venv/bin/pip" install \
    --quiet \
    --target "$OUT" \
    --platform manylinux2014_aarch64 \
    --implementation cp \
    --python-version 3.13 \
    --only-binary=:all: \
    "fsrs>=5.0" "mcp>=1.9" "mangum>=0.19"

cp -R "$ROOT/src/yomu" "$OUT/yomu"

# Keep *.dist-info: mcp resolves its own version via importlib.metadata at
# import time and dies without it.
find "$OUT" -type d -name "__pycache__" -prune -exec rm -rf {} +

echo "Lambda asset built at $OUT ($(du -sh "$OUT" | cut -f1))"
