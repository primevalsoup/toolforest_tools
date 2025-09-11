from __future__ import annotations

import re
from typing import Annotated

from pydantic import StringConstraints

# Non-empty signature and basic length guards (header >=10, payload >=10, signature >=32)
JWT_REGEX_STRICT_LEN = r"^[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{32,}$"

JwtTokenStr = Annotated[str, StringConstraints(pattern=JWT_REGEX_STRICT_LEN)]

_jwt_re = re.compile(JWT_REGEX_STRICT_LEN)


def is_jwt_format(token: str) -> bool:
    return bool(_jwt_re.match(token or ""))
