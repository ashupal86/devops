from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Profile
from app.schemas import (
    ProfileCreate,
    ProfileCreated,
    ProfileOut,
    ProfileUpdate,
    TagAvailability,
    normalize_tag,
    validate_tag,
)
from app.security import hash_token, new_edit_token, token_matches

router = APIRouter(prefix="/api/profiles", tags=["profiles"])

DbSession = Annotated[Session, Depends(get_db)]


def _release(db: Session) -> None:
    """Return the session's connection to the pool before the handler returns.

    For a sync route FastAPI serializes the response in the shared
    threadpool, and get_db only closes the session after that. Under
    load every thread was blocked waiting for a pooled connection while
    the requests holding connections waited for a thread to serialize
    their response, so the pool ran dry with RDS idle. Profile has only
    column attributes, so the detached instance serializes without the
    session.
    """
    db.close()


def _find(db: Session, tag: str) -> Profile | None:
    return db.scalar(select(Profile).where(Profile.tag == normalize_tag(tag)))


def _get_or_404(db: Session, tag: str) -> Profile:
    profile = _find(db, tag)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profile not found")
    return profile


def _authorized_profile(
    tag: str,
    db: DbSession,
    x_edit_token: Annotated[str | None, Header()] = None,
) -> Profile:
    profile = _get_or_404(db, tag)
    if not x_edit_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing X-Edit-Token header")
    if not token_matches(x_edit_token, profile.edit_token_hash):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid edit token")
    return profile


@router.get("/{tag}/available", response_model=TagAvailability)
def check_tag(tag: str, db: DbSession) -> TagAvailability:
    try:
        normalized = validate_tag(tag)
    except ValueError as exc:
        return TagAvailability(tag=normalize_tag(tag), available=False, reason=str(exc))
    taken = _find(db, normalized) is not None
    _release(db)
    if taken:
        return TagAvailability(tag=normalized, available=False, reason="already taken")
    return TagAvailability(tag=normalized, available=True)


@router.post("", response_model=ProfileCreated, status_code=status.HTTP_201_CREATED)
def create_profile(payload: ProfileCreate, db: DbSession) -> ProfileCreated:
    if _find(db, payload.tag) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Tag already taken")

    token = new_edit_token()
    profile = Profile(
        tag=payload.tag,
        display_name=payload.display_name,
        message=payload.message,
        links=[link.model_dump() for link in payload.links],
        edit_token_hash=hash_token(token),
    )
    db.add(profile)
    try:
        db.commit()
    except IntegrityError:
        # Lost a race with a concurrent create for the same tag.
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Tag already taken")
    db.refresh(profile)
    _release(db)
    return ProfileCreated(profile=ProfileOut.model_validate(profile), edit_token=token)


@router.get("/{tag}", response_model=ProfileOut)
def get_profile(tag: str, db: DbSession) -> Profile:
    profile = _get_or_404(db, tag)
    _release(db)
    return profile


@router.put("/{tag}", response_model=ProfileOut)
def update_profile(
    payload: ProfileUpdate,
    db: DbSession,
    profile: Annotated[Profile, Depends(_authorized_profile)],
) -> Profile:
    profile.display_name = payload.display_name
    profile.message = payload.message
    profile.links = [link.model_dump() for link in payload.links]
    db.commit()
    db.refresh(profile)
    _release(db)
    return profile


@router.delete("/{tag}", status_code=status.HTTP_204_NO_CONTENT)
def delete_profile(
    db: DbSession,
    profile: Annotated[Profile, Depends(_authorized_profile)],
) -> Response:
    db.delete(profile)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
