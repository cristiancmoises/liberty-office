import re
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Identity(Model):
    username: str = Field(min_length=3,max_length=48)
    name: str = Field(min_length=1,max_length=100)

    @field_validator('username')
    @classmethod
    def username_valid(cls, value):
        value=value.strip().lower()
        if not re.fullmatch(r'[a-z0-9][a-z0-9._-]{2,47}',value):
            raise ValueError('Use letras, números, ponto, hífen ou sublinhado.')
        return value


class Bootstrap(Identity):
    token: str = Field(min_length=20,max_length=200)
    password: str = Field(min_length=14,max_length=256)


class Activate(Model):
    token: str = Field(min_length=20,max_length=200)
    password: str = Field(min_length=14,max_length=256)


class Login(Model):
    username: str = Field(min_length=1,max_length=48)
    password: str = Field(min_length=1,max_length=256)


class Code(Model):
    code: str = Field(min_length=6,max_length=100)


class Password(Model):
    current_password: str = Field(min_length=1,max_length=256)
    password: str = Field(min_length=14,max_length=256)


class Reauth(Model):
    password: str = Field(min_length=1,max_length=256)
    code: str = Field(min_length=6,max_length=6)


class NewUser(Identity):
    quota: int | None = Field(default=None,ge=0,le=2**60)
    role: str = Field(default='user',pattern=r'^(admin|user)$')


class UserPatch(Model):
    name: str | None = Field(default=None,min_length=1,max_length=100)
    quota: int | None = Field(default=None,ge=0,le=2**60)
    role: str | None = Field(default=None,pattern=r'^(admin|user)$')
    enabled: bool | None = None
