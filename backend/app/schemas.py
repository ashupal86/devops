import re
from datetime import datetime
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

TAG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9_-]{1,28})[a-z0-9]$")
RESERVED_TAGS = frozenset({"api", "new", "edit", "admin", "health", "ready", "static", "assets"})
MAX_LINKS = 20


def normalize_tag(value: str) -> str:
    return value.strip().lower()


def validate_tag(value: str) -> str:
    tag = normalize_tag(value)
    if not TAG_RE.match(tag):
        raise ValueError(
            "tag must be 3-30 chars of a-z, 0-9, '-' or '_', "
            "and start and end with a letter or digit"
        )
    if tag in RESERVED_TAGS:
        raise ValueError(f"'{tag}' is reserved")
    return tag


class Link(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    label: str = Field(min_length=1, max_length=40)
    url: str = Field(min_length=1, max_length=2048)

    @field_validator("url")
    @classmethod
    def _http_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("url must be an absolute http(s) URL")
        return value


class ProfileFields(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    display_name: str = Field(min_length=1, max_length=80)
    message: str = Field(default="", max_length=500)
    links: list[Link] = Field(default_factory=list, max_length=MAX_LINKS)


class ProfileCreate(ProfileFields):
    tag: str

    @field_validator("tag")
    @classmethod
    def _tag(cls, value: str) -> str:
        return validate_tag(value)


class ProfileUpdate(ProfileFields):
    pass


class ProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tag: str
    display_name: str
    message: str
    links: list[Link]
    created_at: datetime
    updated_at: datetime


class ProfileCreated(BaseModel):
    profile: ProfileOut
    edit_token: str


class TagAvailability(BaseModel):
    tag: str
    available: bool
    reason: str | None = None
