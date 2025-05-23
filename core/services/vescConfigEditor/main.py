#! /usr/bin/env python3
import logging
import os
from typing import Any, List

import uvicorn
from commonwealth.utils.apis import GenericErrorHandlingRoute
from commonwealth.utils.logs import InterceptHandler, init_logger
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi_versioning import VersionedFastAPI, version
from loguru import logger

from vescConfigEditor import AppConfigData, vescConfigEditor

SERVICE_NAME = "vescConfigEditor"

logging.basicConfig(handlers=[InterceptHandler()], level=0)
init_logger(SERVICE_NAME)

app = FastAPI(
    title="Vesc config editor API",
    description="Vesc config editor is a service that handles config editing on the motor controllers.",
)
app.router.route_class = GenericErrorHandlingRoute
logger.info("Starting vescConfigEditor!")

controller = vescConfigEditor()
logger.info("VESC Config Editor initialized.")


@app.get("/serial_ports", response_model=List[str])
@version(1, 0)
def get_serial_ports() -> Any:
    ports = controller.available_serial_ports()
    logger.debug(f"Available serial ports found: {ports}.")
    return ports


@app.post("/changeTimeout", status_code=200)
@version(1, 0)
async def change_timeout(serial_path: str, timeout_seconds: int) -> Any:
    logger.debug(f"Changing timeout to {timeout_seconds}.")
    controller.change_timeout(serial_path, timeout_seconds)
    logger.debug(f"Timeout changed to {timeout_seconds}.")


@app.get("/getAppConfig", response_model=AppConfigData)
@version(1, 0)
async def get_app_config(serial_path: str) -> AppConfigData:
    logger.debug(f"Getting app config from {serial_path}.")
    app_config = controller.get_app_config(serial_path)
    logger.debug(f"App config retrieved: {app_config}.")
    return app_config


app = VersionedFastAPI(app, version="1.0.0", prefix_format="/v{major}.{minor}", enable_latest=True)


@app.get("/")
async def root() -> Any:
    html_content = """
    <html>
        <head>
            <title>vescConfigEditor</title>
        </head>
    </html>
    """
    return HTMLResponse(content=html_content, status_code=200)


if __name__ == "__main__":
    # Running uvicorn with log disabled so loguru can handle it
    uvicorn.run(app, host="0.0.0.0", port=35679, log_config=None)
