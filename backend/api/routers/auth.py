from fastapi import APIRouter, HTTPException, status

from api.auth import CurrentUserDep
from api.auth.tokens import create_access_token
from api.config import get_settings
from api.db.deps import SessionDep
from api.models import User
from api.schemas import LoginRequest, TokenResponse, UserRead
from api.service.database import DatabaseGateDep
from api.service.users import authenticate

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(data: LoginRequest, session: SessionDep, gate: DatabaseGateDep) -> TokenResponse:
    password = data.password.get_secret_value()
    user = await authenticate(session, data.email, password, detached=not gate.ready)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    ttl = get_settings().access_token_ttl
    token = create_access_token(user.id, user.token_version, ttl)
    return TokenResponse(access_token=token, expires_in=int(ttl.total_seconds()))


@router.get("/me", response_model=UserRead)
async def me(user: CurrentUserDep) -> User:
    return user
