#! /usr/bin/env python3
import logging
import os
from typing import Any, List

import uvicorn
from commonwealth.utils.apis import GenericErrorHandlingRoute
from commonwealth.utils.logs import InterceptHandler, init_logger
from fastapi.responses import HTMLResponse
from fastapi import FastAPI
from fastapi_versioning import VersionedFastAPI, version
from loguru import logger
from vescConfigEditor.vescConfigEditor import vescConfigEditor

SERVICE_NAME = "vescConfigEditor"
LOG_FOLDER_PATH = os.environ.get("BLUEOS_LOG_FOLDER_PATH", "/var/logs/blueos")
MAVLINK_LOG_FOLDER_PATH = os.environ.get("BLUEOS_MAVLINK_LOG_FOLDER_PATH", "/shortcuts/ardupilot_logs/logs/")

logging.basicConfig(handlers=[InterceptHandler()], level=0)
init_logger(SERVICE_NAME)

app = FastAPI(
    title="Commander API",
    description="Commander is a BlueOS service responsible to abstract simple commands to the frontend.",
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
async def change_timeout(serial_path: str, timeout: int) -> Any:
    logger.debug(f"Changing timeout to {timeout}.")
    controller.change_timeout(serial_path, timeout)
    logger.debug(f"Timeout changed to {timeout}.")


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
