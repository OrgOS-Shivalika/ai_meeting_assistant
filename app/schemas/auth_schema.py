from typing import ClassVar

from pydantic import BaseModel, EmailStr

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

    _password_fields: ClassVar[tuple[str, ...]] = ("password",)

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
