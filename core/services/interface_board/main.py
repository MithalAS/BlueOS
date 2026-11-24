#! /usr/bin/env python3
import logging
from typing import Any, Callable

from commonwealth.utils.apis import GenericErrorHandlingRoute
from commonwealth.utils.logs import InterceptHandler, init_logger
from fastapi import FastAPI, HTTPException
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse
from fastapi_versioning import VersionedFastAPI, version
from loguru import logger
from starlette.routing import Mount

from fuseboard import (
    BoardStatus,
    DeviceNotFound,
    Fuse,
    ModbusError,
    ModbusTimeout,
    StateMismatch,
    board_from_environment,
)

SERVICE_NAME = "interface_board"

logging.basicConfig(handlers=[InterceptHandler()], level=0)
init_logger(SERVICE_NAME)

app = FastAPI(
    title="Interface Board API",
    description="Interface Board is a service that reads and controls the smart fuses on the POD interface board.",
)
app.router.route_class = GenericErrorHandlingRoute
logger.info("Starting interface board!")

board = board_from_environment()


def run(action: Callable[[], Any]) -> Any:
    try:
        return action()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except StateMismatch as e:
        raise HTTPException(status_code=409, detail={"message": str(e), "status": e.status.dict()}) from e
    except DeviceNotFound as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except ModbusTimeout as e:
        raise HTTPException(status_code=504, detail=str(e)) from e
    except ModbusError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.get("/status", response_model=BoardStatus)
@version(1, 0)
def get_status() -> Any:
    return run(board.status)


@app.get("/fuses", response_model=list[Fuse])
@version(1, 0)
def get_fuses() -> Any:
    return run(lambda: board.status().fuses)


@app.get("/fuses/{channel}", response_model=Fuse)
@version(1, 0)
def get_fuse(channel: int) -> Any:
    return run(lambda: board.fuse(channel))


@app.post("/fuses/reset_all")
@version(1, 0)
def reset_all() -> Any:
    run(board.reset_all)


@app.post("/fuses/{channel}/enable", response_model=Fuse)
@version(1, 0)
def set_enabled(channel: int, enabled: bool) -> Any:
    logger.info(f"Setting fuse {channel} enabled={enabled}")
    return run(lambda: board.set_enabled(channel, enabled))


@app.post("/fuses/{channel}/reset_fault")
@version(1, 0)
def reset_fault(channel: int) -> Any:
    run(lambda: board.reset_fault(channel))


@app.post("/reboot")
@version(1, 0)
def reboot() -> Any:
    run(board.reboot)


@app.post("/reboot_dfu")
@version(1, 0)
def reboot_dfu() -> Any:
    run(board.reboot_dfu)


@app.post("/slave_address")
@version(1, 0)
def set_slave_address(address: int) -> Any:
    run(lambda: board.set_slave_address(address))


app = VersionedFastAPI(app, version="1.0.0", prefix_format="/v{major}.{minor}", enable_latest=True)
app.add_event_handler("shutdown", board.close)
for route in app.routes:
    if isinstance(route, Mount) and isinstance(route.app, FastAPI):
        route.app.root_path_in_servers = False
        route.app.servers = [{"url": "."}]


@app.get("/api-docs", include_in_schema=False)
def api_docs() -> HTMLResponse:
    return get_swagger_ui_html(openapi_url="v1.0/openapi.json", title="Interface Board API")


@app.get("/")
async def root() -> Any:
    return HTMLResponse(content="<html><head><title>Interface Board</title></head></html>", status_code=200)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=9113, log_config=None)
