"""
User/auth schemas.

These Pydantic models define the request and response shape for authentication and
profile-related APIs. The password hash itself is never part of any response model.
"""

import re
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

# A pragmatic, not-exhaustive minimum: at least 8 characters, one letter, one digit. This is a
# basic strength gate, not a full password-policy engine.
_PASSWORD_PATTERN = re.compile(r"^(?=.*[A-Za-z])(?=.*\d).{8,}$")


class UserCreateRequest(BaseModel):
    """
    Request body for manual sign-up (email + contact number + password).
    """
    email: EmailStr = Field(..., example="user@example.com")
    contact_number: str = Field(..., example="+1 555-123-4567")
    password: str = Field(..., example="Str0ngPass!")
    confirm_password: str = Field(..., example="Str0ngPass!")

    @field_validator("password")
    @classmethod
    def _password_strength(cls, value: str) -> str:
        if not _PASSWORD_PATTERN.match(value):
            raise ValueError("Password must be at least 8 characters and include a letter and a digit.")
        return value

    @model_validator(mode="after")
    def _passwords_match(self) -> "UserCreateRequest":
        if self.password != self.confirm_password:
            raise ValueError("Password and confirm password do not match.")
        return self


class UserLoginRequest(BaseModel):
    """
    Request body for email/password sign-in.
    """
    email: EmailStr = Field(..., example="user@example.com")
    password: str = Field(..., example="Str0ngPass!")


class ProfileUpdateRequest(BaseModel):
    """
    Request body for updating the signed-in user's own profile. All fields optional -- only
    the ones the user actually changed need to be sent.
    """
    name: str | None = Field(default=None, example="Dulneth Santhuka")
    contact_number: str | None = Field(default=None, example="+1 555-123-4567")
    profile_picture_url: str | None = Field(default=None, example="https://example.com/avatar.png")


class PasswordUpdateRequest(BaseModel):
    """
    Request body for changing the signed-in user's own password. Rejected for an OAuth-only
    account (no existing password to confirm against).
    """
    current_password: str = Field(..., example="OldPass1")
    new_password: str = Field(..., example="NewPass2")

    @field_validator("new_password")
    @classmethod
    def _password_strength(cls, value: str) -> str:
        if not _PASSWORD_PATTERN.match(value):
            raise ValueError("Password must be at least 8 characters and include a letter and a digit.")
        return value


class UserResponse(BaseModel):
    """
    API response for the signed-in user's own record. Never includes the password hash.
    """
    user_id: str
    email: str
    contact_number: str | None = None
    name: str | None = None
    profile_picture_url: str | None = None
    auth_provider: str = "password"
    created_at: datetime
    updated_at: datetime


class TokenResponse(BaseModel):
    """
    API response returned after a successful register/login -- the frontend stores
    access_token and sends it as an `Authorization: Bearer <access_token>` header.
    """
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
