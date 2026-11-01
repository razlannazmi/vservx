from pydantic import BaseModel

from api.enums import DatabaseState


class HealthResponse(BaseModel):
    status: str
    version: str
    # Public so the sign-in page can already say an upgrade is waiting.
    database: DatabaseState
    # Public so the sign-in page can hide "Create an account" while sign-up is off.
    signup_open: bool
