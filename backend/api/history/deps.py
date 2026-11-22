from typing import Annotated

from fastapi import Depends, Request

from api.history.types import HistoryStore


def get_history(request: Request) -> HistoryStore:
    return request.app.state.history


HistoryDep = Annotated[HistoryStore, Depends(get_history)]
