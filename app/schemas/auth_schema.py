from typing import ClassVar

from pydantic import BaseModel, EmailStr, Field

from app.utils.password_transport import EncodedPasswordModel

class UserBase(BaseModel):
    email: EmailStr
    name: str

class UserCreate(UserBase, EncodedPasswordModel):
    password: str

    _password_fields: ClassVar[tuple[str, ...]] = ("password",)

class UserLogin(EncodedPasswordModel):
    email: EmailStr
    password: str
    # "Keep me signed in". Decides whether the browser gets a persistent
    # cookie or a session one; defaults True so an older client that does not
    # send the field keeps the behaviour it has today.
    remember_me: bool = True

    _password_fields: ClassVar[tuple[str, ...]] = ("password",)

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ForgotPasswordRequest(BaseModel):
    """POST /public/auth/forgot-password.

    `EmailStr`, not `str`, so a malformed address is rejected before it
    reaches a lookup. Note the response is identical either way — validation
    shape is not an enumeration signal, but the ANSWER must never be.
    """

    email: EmailStr


class ResetPasswordRequest(EncodedPasswordModel):
    """POST /public/auth/reset-password.

    The token is a raw opaque string; only `new_password` goes through the
    base64 envelope, matching every other password-carrying request. The
    8..128 rule is enforced on the DECODED value by `_password_rules`.
    """

    token: str = Field(min_length=16, max_length=512)
    new_password: str = Field(max_length=1024)

    _password_fields: ClassVar[tuple[str, ...]] = ("new_password",)
    _password_rules: ClassVar[dict[str, tuple[int, int]]] = {
        "new_password": (8, 128),
    }
