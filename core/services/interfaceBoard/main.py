#! /usr/bin/env python3
import logging
from typing import List

from commonwealth.utils.logs import InterceptHandler, init_logger
from fastapi import FastAPI, HTTPException, Path
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi_versioning import VersionedFastAPI, version
from pydantic import BaseModel, StrictBool
from starlette.responses import HTMLResponse
from starlette.routing import Mount

from board import BoardError, StateMismatch, board_from_environment


class Channel(BaseModel):
    number: int
    name: str
    enabled: bool
    fault: bool
    current_ma: int


class BoardStatus(BaseModel):
    firmware: str
    channels: List[Channel]


class ChannelState(BaseModel):
    enabled: StrictBool


logging.basicConfig(handlers=[InterceptHandler()], level=0)
init_logger("interfaceBoard")

board = board_from_environment()
app = FastAPI(title="Interface Board API", description="Status and power control for the Remora POD interface board.")


@app.get("/board", response_model=BoardStatus)
@version(1, 0)
def get_board() -> BoardStatus:
    try:
        return BoardStatus(**board.snapshot())
    except BoardError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.put("/channels/{channel}", response_model=BoardStatus)
@version(1, 0)
def set_channel(state: ChannelState, channel: int = Path(..., ge=1, le=5)) -> BoardStatus:
    try:
        return BoardStatus(**board.set_channel(channel, state.enabled))
    except StateMismatch as error:
        raise HTTPException(status_code=409, detail={"message": str(error), "status": error.status}) from error
    except BoardError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


app = VersionedFastAPI(app, version="1.0.0", prefix_format="/v{major}.{minor}", enable_latest=True)
app.add_event_handler("shutdown", board.close)
for route in app.routes:
    if isinstance(route, Mount) and isinstance(route.app, FastAPI):
        route.app.root_path_in_servers = False
        route.app.servers = [{"url": "."}]


@app.get("/api-docs", include_in_schema=False)
def api_docs() -> HTMLResponse:
    return get_swagger_ui_html(openapi_url="v1.0/openapi.json", title="Interface Board API")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=9113)
