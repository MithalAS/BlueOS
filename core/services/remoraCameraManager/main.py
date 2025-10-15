#! /usr/bin/env python3
import logging
from typing import Any, List

import uvicorn
from commonwealth.utils.apis import GenericErrorHandlingRoute
from commonwealth.utils.logs import InterceptHandler, init_logger
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi_versioning import VersionedFastAPI, version
from loguru import logger

from remoraCameraManager import RemoraCameraManager

SERVICE_NAME = "remoraCameraManager"

logging.basicConfig(handlers=[InterceptHandler()], level=0)
init_logger(SERVICE_NAME)

app = FastAPI(
    title="remoraCameraManager",
    description="Remora camera manager is a service that handles camera streams and settings.",
)
app.router.route_class = GenericErrorHandlingRoute
logger.info("Starting remoraCameraManager!")

manager = RemoraCameraManager()
logger.info(" Editor initialized.")


@app.get("/video_ports", response_model=List[str])
@version(1, 0)
def get_video_ports() -> Any:
    ports = manager.available_video_ports()
    logger.debug(f"Available video ports found: {ports}.")
    return ports


@app.get("/uhubctrl_printout", response_model=List[str])
@version(1, 0)
def get_uhubctrl_printout() -> Any:
    try:
        output = manager.get_uhubctrl_printout()
        logger.debug(f"uhubctl printout: {output}.")
        return output
    except Exception as e:
        logger.error(f"Error getting uhubctl printout: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}") from e


@app.post("/powerCyclePort", response_model=dict)
def power_cycle_port(port: int, location: str = "1-1", duration: int = 2) -> Any:
    try:
        manager.usbControl.power_cycle(location, port, duration)
        message = f"Port {port} power cycled for {duration} seconds."
        logger.debug(message)
        return {"message": message}
    except Exception as e:
        logger.error(f"Error power cycling port {port}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}") from e


@app.post("/powerCycleCamera", response_model=dict)
def power_cycle_camera(camera: str) -> Any:
    try:
        manager.power_cycle_camera(camera)
        message = f"Camera '{camera}' power cycled."
        logger.debug(message)
        return {"message": message}
    except ValueError as ve:
        logger.error(f"Value error: {ve}")
        raise HTTPException(status_code=422, detail=str(ve)) from ve
    except Exception as e:
        logger.error(f"Error power cycling camera '{camera}': {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}") from e


@app.post("/startMediaServer", response_model=dict)
def start_media_server() -> Any:
    try:
        manager.start_mediamtx_server()
        message = "Media server started."
        logger.debug(message)
        return {"message": message}
    except Exception as e:
        logger.error(f"Error starting media server: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}") from e


@app.post("/stopMediaServer", response_model=dict)
def stop_media_server() -> Any:
    try:
        manager.stop_media_server()
        message = "Media server stopped."
        logger.debug(message)
        return {"message": message}
    except Exception as e:
        logger.error(f"Error stopping media server: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}") from e


@app.post("/restartMediaServer", response_model=dict)
def restart_media_server() -> Any:
    try:
        manager.stop_media_server()
        manager.start_mediamtx_server()
        message = "Media server restarted."
        logger.debug(message)
        return {"message": message}
    except Exception as e:
        logger.error(f"Error restarting media server: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}") from e


@app.post("/startStream", response_model=dict)
def start_stream(camera: str) -> Any:
    try:
        manager.start_stream(camera)
        message = f"Stream for camera '{camera}' started."
        logger.debug(message)
        return {"message": message}
    except ValueError as ve:
        logger.error(f"Value error: {ve}")
        raise HTTPException(status_code=422, detail=str(ve)) from ve
    except Exception as e:
        logger.error(f"Error starting stream for camera '{camera}': {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}") from e


@app.post("/stopStream", response_model=dict)
def stop_stream(camera: str) -> Any:
    try:
        manager.stop_stream(camera)
        message = f"Stream for camera '{camera}' stopped."
        logger.debug(message)
        return {"message": message}
    except ValueError as ve:
        logger.error(f"Value error: {ve}")
        raise HTTPException(status_code=422, detail=str(ve)) from ve
    except Exception as e:
        logger.error(f"Error stopping stream for camera '{camera}': {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}") from e


@app.get("/video_devices", response_model=List[str])
@version(1, 0)
def get_video_devices(
    pixel_format: str = "H264", size: str = "640x480", device_glob: str = "/dev/video*", include_alias: bool = False
) -> Any:
    try:
        devices = manager.find_video_devices(pixel_format, size, device_glob, include_alias)
        logger.debug(f"Video devices found: {devices}.")
        return devices
    except Exception as e:
        logger.error(f"Error finding video devices: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}") from e


@app.get("/config", response_model=Any)
def get_config() -> Any:
    try:
        config = manager.get_config()
        logger.debug(f"Configuration retrieved: {config}.")
        return config
    except Exception as e:
        logger.error(f"Error retrieving configuration: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}") from e


@app.post("/config", response_model=dict[str, Any])
def update_config(new_config: dict[str, Any]) -> Any:
    try:
        manager.set_config(new_config)
        updated_config = manager.get_config()
        logger.debug(f"Configuration updated to: {updated_config}.")
        return updated_config
    except Exception as e:
        logger.error(f"Error updating configuration: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}") from e


@app.post("/config/default", response_model=dict)
def reset_config_to_default() -> Any:
    try:
        manager.set_default_config()
        default_config = manager.get_config()
        logger.debug(f"Configuration reset to default: {default_config}.")
        return default_config
    except Exception as e:
        logger.error(f"Error resetting configuration to default: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}") from e


app = VersionedFastAPI(app, version="1.0.0", prefix_format="/v{major}.{minor}", enable_latest=True)


@app.get("/")
async def root() -> Any:
    html_content = """
    <html>
        <head>
            <title>Remora Camera Manager</title>
        </head>
    </html>
    """
    return HTMLResponse(content=html_content, status_code=200)


if __name__ == "__main__":
    # Running uvicorn with log disabled so loguru can handle it
    uvicorn.run(app, host="0.0.0.0", port=9112, log_config=None)
