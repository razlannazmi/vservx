from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import exists, select

from api.auth import CurrentUserDep, revoke_tokens
from api.auth.deps import clear_session_cookie, set_session_cookie
from api.auth.password import hash_password, verify_password
from api.auth.tokens import create_access_token
from api.config import get_settings
from api.db.deps import SessionDep
from api.enums import UserRole
from api.models import User
from api.schemas import LoginRequest, TokenResponse, UserRead
from api.schemas.account import PasswordChange, ProfileUpdate, SignupRequest
from api.service.database import DatabaseGateDep, DatabaseNotReady, require_current_database
from api.service.users import authenticate, signup_open

router = APIRouter(prefix="/auth", tags=["auth"])

# Routes that write to the users table need its newest shape.
_current_database = [Depends(require_current_database)]


def _sign_in(user: User, request: Request, response: Response) -> TokenResponse:
    """A token for the response body (scripts) and the session cookie (the web app)."""
    ttl = get_settings().access_token_ttl
    token = create_access_token(user.id, user.token_version, ttl)
    expires_in = int(ttl.total_seconds())
    set_session_cookie(response, request, token, expires_in)
    return TokenResponse(access_token=token, expires_in=expires_in)


@router.post("/login", response_model=TokenResponse)
async def login(
    data: LoginRequest, request: Request, response: Response, session: SessionDep, gate: DatabaseGateDep
) -> TokenResponse:
    password = data.password.get_secret_value()
    user = await authenticate(session, data.email, password, detached=not gate.ready)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # While an upgrade waits, only admins (who can run it) get in; nobody else could do anything.
    if not gate.ready and user.role is not UserRole.ADMIN:
        assert gate.status is not None
        raise DatabaseNotReady(gate.status.state)
    return _sign_in(user, request, response)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response) -> None:
    """Forget the browser's session. Bearer tokens simply stop being sent."""
    clear_session_cookie(response, request)


@router.post("/signup", status_code=status.HTTP_202_ACCEPTED, dependencies=_current_database)
async def sign_up(data: SignupRequest, session: SessionDep) -> dict[str, str]:
    """Ask for an account. It can't sign in until an app admin approves it."""
    if not await signup_open(session):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sign-up is turned off")
    # Saying so spares someone with a typo from waiting for an approval that never comes.
    if await session.scalar(select(exists().where(User.email == data.email))):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That email is already registered")
    password_hash = await run_in_threadpool(hash_password, data.password.get_secret_value())
    session.add(User(name=data.name, email=data.email, password_hash=password_hash, role=UserRole.MEMBER))
    await session.commit()
    return {"detail": "An admin needs to approve your account before you can sign in."}


@router.get("/me", response_model=UserRead)
async def me(user: CurrentUserDep) -> User:
    return user


@router.patch("/me", response_model=UserRead, dependencies=_current_database)
async def update_me(data: ProfileUpdate, user: CurrentUserDep, session: SessionDep) -> User:
    user.name = data.name
    await session.commit()
    return user


@router.post("/me/password", response_model=TokenResponse, dependencies=_current_database)
async def change_my_password(
    data: PasswordChange, user: CurrentUserDep, request: Request, response: Response, session: SessionDep
) -> TokenResponse:
    """Change your own password. Every other session is signed out; this one gets a new token."""
    if not await run_in_threadpool(verify_password, user.password_hash, data.current_password.get_secret_value()):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    user.password_hash = await run_in_threadpool(hash_password, data.new_password.get_secret_value())
    revoke_tokens(user)
    await session.commit()
    return _sign_in(user, request, response)
