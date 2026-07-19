"""Lambda entrypoint: `yomu.lambda_handler.handler`."""

from yomu.server import build_handler

handler = build_handler()
