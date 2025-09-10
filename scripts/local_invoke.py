#!/usr/bin/env python3
from __future__ import annotations

import json
import sys

from toolsets.math.src.lambda_handler import handler


def main() -> None:
    event = json.loads(sys.stdin.read())
    resp = handler(event, None)
    print(json.dumps(resp))


if __name__ == "__main__":
    main()
