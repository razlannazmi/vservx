from pydantic import BaseModel

from api.enums import DatabaseState


class HealthResponse(BaseModel):
    status: str
    version: str
    # Public so the sign-in page can already say an upgrade is waiting.
    database: DatabaseState
