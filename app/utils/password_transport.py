
from __future__ import annotations

import base64
import binascii
from typing import ClassVar

from fastapi import HTTPException, status
from pydantic import BaseModel, model_validator

MAX_DECODED_BYTES = 512


def decode_password(value: str, *, field: str = "password") -> str:
    """Return the plaintext password for a base64 `value`.

    Decoded strictly — malformed input raises 422 rather than sliding
    through as a wrong-looking password, so a client that forgot to encode
    reads as a client bug instead of an authentication failure.
    """
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field} is not valid base64",
        ) from exc

    if len(raw) > MAX_DECODED_BYTES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field} exceeds the maximum encoded length",
        )

    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field} did not decode to valid UTF-8 text",
        ) from exc


class EncodedPasswordModel(BaseModel):
    """Mixin that decodes its password fields in place after validation.

    Subclasses list the fields to decode in `_password_fields`. Because
    the work happens during model validation, every route and service
    downstream keeps reading `.password` and gets plaintext — no call site
    needs to know transport encoding exists.

    Subclasses that declare a length rule on a password field must repeat
    it in `_password_rules`. Pydantic checks `Field(min_length=...)`
    against the value as it arrived on the wire, which is the *encoded*
    string — `b64encode("abcd")` is `"YWJjZA=="`, eight characters, which
    sails past `min_length=8` while the real password is four. Re-checking
    after the decode is what actually enforces the policy.
    """

    # Overridden per subclass.
    _password_fields: ClassVar[tuple[str, ...]] = ("password",)

    # field -> (min_length, max_length). Fields left out get no check.
    _password_rules: ClassVar[dict[str, tuple[int, int]]] = {}

    @model_validator(mode="after")
    def _decode_passwords(self):
        for field in self._password_fields:
            current = getattr(self, field, None)
            if not isinstance(current, str):
                continue

            decoded = decode_password(current, field=field)

            rule = self._password_rules.get(field)
            if rule is not None:
                minimum, maximum = rule
                if not (minimum <= len(decoded) <= maximum):
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=(
                            f"{field} must be between {minimum} and "
                            f"{maximum} characters"
                        ),
                    )

            # Bypasses re-validation on purpose: the declared Field rules
            # describe the wire value, and we've just replaced it with the
            # decoded one (re-running them here would re-reject a decoded
            # password that is legitimately shorter than its encoding).
            object.__setattr__(self, field, decoded)

        return self
