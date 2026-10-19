#! /usr/bin/env python3
import logging
from typing import Any, Callable

import uvicorn
from commonwealth.utils.apis import GenericErrorHandlingRoute
from commonwealth.utils.logs import InterceptHandler, init_logger
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi_versioning import VersionedFastAPI, version
from loguru import logger

from fuseboard import (
    BoardStatus,
    DeviceNotFound,
    Fuse,
    FuseBoard,
    ModbusError,
    ModbusTimeout,
)

SERVICE_NAME = "modbus"

logging.basicConfig(handlers=[InterceptHandler()], level=0)
init_logger(SERVICE_NAME)

app = FastAPI(
    title="Modbus API",
    description="Modbus is a service that reads and controls the smart fuses on the POD interface board.",
)
app.router.route_class = GenericErrorHandlingRoute
logger.info("Starting modbus!")

board = FuseBoard()


def run(action: Callable[[], Any]) -> Any:
    try:
        return action()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except DeviceNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
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


@app.get("/")
async def root() -> Any:
    return HTMLResponse(content="<html><head><title>modbus</title></head></html>", status_code=200)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9113, log_config=None)
