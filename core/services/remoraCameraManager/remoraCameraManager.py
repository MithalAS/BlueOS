import glob
import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any, Dict, cast

from commonwealth.settings.manager import Manager
from pykson import Pykson

import usbPortControl
from settings import CameraConfig, SettingsV1

SERVICE_NAME = "remoraCameraManager"

USERDATA = Path("/usr/blueos/userdata/")

pyk = Pykson()
default_config: Dict[str, Any] = {
    "PORT": 8554,
    "IP": "0.0.0.0",
    "USE_HW_ENC": False,
    "USB_HUB": "1-1",
    "FRONT": {
        "usb_hub_port": 2,
        "device": "/dev/video4",
        "resolution": "640x480",
        "fps": 25,
        "name": "front",
        "kbitrate": 1000,
        "preset": "superfast",
    },
    "BACK": {
        "usb_hub_port": 1,
        "device": "/dev/video0",
        "resolution": "640x480",
        "fps": 25,
        "name": "back",
        "kbitrate": 1300,
        "preset": "ultrafast",
    },
}


class RemoraCameraManager:
    """Manager for config changes on remora camera controllers."""

    def __init__(self) -> None:
        self.settings_manager = Manager(SERVICE_NAME, SettingsV1, USERDATA / "settings" / SERVICE_NAME)
        self.settings_manager.load()
        if not self.settings_manager.settings.camera:
            self.settings_manager.settings.camera = pyk.from_json(default_config, CameraConfig)
            self.settings_manager.save()

        self.usbControl = usbPortControl.Uhubctl(use_sudo=False)

    def set_default_config(self) -> None:
        """Set the camera configuration to default values."""
        self.settings_manager.settings.camera = pyk.from_json(default_config, CameraConfig)
        self.settings_manager.save()

    def get_config(self) -> Any:
        """Return the current camera configuration."""
        return json.loads(pyk.to_json(self.settings_manager.settings.camera))

    def set_config(self, new_config: dict[str, Any]) -> None:
        self.settings_manager.settings.camera = pyk.from_json(new_config, CameraConfig)
        self.settings_manager.save()

    def available_video_ports(self) -> list[str]:
        """Return a list of available video ports."""
        video_ports = []
        for device in os.listdir("/dev"):
            if device.startswith("video"):
                video_ports.append(os.path.join("/dev", device))
        return video_ports

    def get_uhubctrl_printout(self) -> list[str]:
        """Return the output of the uhubctl command."""
        try:
            result = subprocess.run(["uhubctl"], capture_output=True, text=True, check=True)
            return result.stdout.splitlines()
        except FileNotFoundError as exc:
            raise RuntimeError("uhubctl command not found. Please ensure it is installed and in your PATH.") from exc
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"uhubctl command failed with exit code {exc.returncode}: {exc.stderr}") from exc

    def power_cycle_camera(self, camera: str) -> None:
        """Power cycle the specified camera."""
        if camera not in self.settings_manager.settings.camera:
            raise ValueError(f"Camera '{camera}' not found in configuration.")

        cam_config = cast(dict[str, Any], self.settings_manager.settings.camera[camera])
        port = cam_config.get("usb_hub_port")
        location = self.settings_manager.settings.camera.get("USB_HUB")
        duration = 10  # seconds

        if port is None:
            raise ValueError(f"usb_hub_port not defined for camera '{camera}'.")

        self.usbControl.power_cycle(str(location), port, duration)

    def start_mediamtx_server(self) -> None:
        """Start the media server process."""
        if shutil.which("docker"):
            with subprocess.Popen(
                [
                    "docker",
                    "run",
                    "-d",
                    "--rm",
                    "--name",
                    "mediamtx",
                    "-p",
                    f"{self.settings_manager.settings.camera['IP']}:{self.settings_manager.settings.camera['PORT']}:{self.settings_manager.settings.camera['PORT']}",
                    "-v",
                    "/home/pi/mediamtx.yml:/mediamtx.yml:ro",
                    "bluenet/mediamtx:latest",
                    "-f",
                    "/mediamtx.yml",
                ]
            ) as proc:
                proc.wait()
                if proc.returncode != 0:
                    raise RuntimeError(f"Failed to start mediamtx server, exit code {proc.returncode}")
        else:
            raise EnvironmentError("Docker is not installed or not found in PATH.")

    def stop_media_server(self) -> None:
        """Stop the media server process."""
        if shutil.which("docker"):
            subprocess.run(["docker", "stop", "mediamtx"], check=False)
        else:
            raise EnvironmentError("Docker is not installed or not found in PATH.")

    def ffmpeg_cmd(self, cam_config: dict[str, Any], use_hw: bool) -> list[str]:
        device = cam_config.get("device")
        res = cam_config.get("resolution")
        fps = cam_config.get("fps")
        kbitrate = cam_config.get("kbitrate")
        preset = cam_config.get("preset")

        input_format = "yuyv422"
        bitrate = f"{kbitrate}k"
        if device is None or res is None or fps is None or kbitrate is None or preset is None:
            raise ValueError("Camera configuration is incomplete.")

        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "info",
            "-thread_queue_size",
            "512",
            "-f",
            "v4l2",
            "-input_format",
            input_format,
            "-video_size",
            res,
            "-framerate",
            str(fps),
            "-i",
            device,
        ]

        # Always end up in yuv420p for H.264 encoders
        cmd += ["-vf", "format=yuv420p"]

        if use_hw:
            print("h264_v4l2m2m encoder selected")
            cmd += [
                "-c:v",
                "h264_v4l2m2m",
                "-pix_fmt",
                "yuv420p",
                "-b:v",
                bitrate,
                "-maxrate",
                str(int(kbitrate) * 1200),
                "-bufsize",
                str(int(kbitrate) * 1500),
                "-g",
                str(fps),
            ]
        else:
            print("libx264 encoder selected")
            cmd += [
                "-c:v",
                "libx264",
                "-preset",
                preset,
                "-profile:v",
                "high",
                "-pix_fmt",
                "yuv420p",
                "-x264-params",
                f"scenecut=0:keyint={fps}:min-keyint={fps}",
                "-b:v",
                bitrate,
                "-maxrate",
                str(int(kbitrate) * 1200),
                "-bufsize",
                str(int(kbitrate) * 2000),
                "-g",
                str(fps),
                "-bf",
                "0",
            ]
        return cmd

    def start_stream(self, camera: str) -> None:
        """Start streaming for the specified camera."""
        if camera not in self.settings_manager.settings.camera:
            raise ValueError(f"Camera '{camera}' not found in configuration.")

        cam_config = cast(dict[str, Any], self.settings_manager.settings.camera[camera])
        device = cam_config.get("device")
        use_hw = self.settings_manager.settings.camera.get("USE_HW_ENC")

        if device is None:
            raise ValueError(f"Device not defined for camera '{camera}'.")

        cmd = self.ffmpeg_cmd(cam_config, bool(use_hw))

        # RTSP output
        rtsp_url = f"rtsp://{self.settings_manager.settings.camera['IP']}:{self.settings_manager.settings.camera['PORT']}/{cam_config['name']}"
        cmd += [
            "-f",
            "rtsp",
            "-rtsp_transport",
            "tcp",
            "-muxdelay",
            "0.1",
            rtsp_url,
        ]

        print(f"Starting stream for camera '{camera}' with command: {' '.join(cmd)}")

        # Start the ffmpeg process
        with subprocess.Popen(cmd) as proc:
            proc.wait()
            if proc.returncode != 0:
                raise RuntimeError(f"ffmpeg exited with code {proc.returncode}")
            print(f"[+] Stream started for camera '{camera}'.")

    def stop_stream(self, camera: str) -> None:
        """Stop streaming for the specified camera."""
        if camera not in self.settings_manager.settings.camera:
            raise ValueError(f"Camera '{camera}' not found in configuration.")

        cam_config = cast(dict[str, Any], self.settings_manager.settings.camera[camera])
        name = cam_config.get("name")

        if name is None:
            raise ValueError(f"Name not defined for camera '{camera}'.")

        # Find and kill the ffmpeg process streaming this camera
        try:
            result = subprocess.run(
                [
                    "pgrep",
                    "-f",
                    f"rtsp://{self.settings_manager.settings.camera['IP']}:{self.settings_manager.settings.camera['PORT']}/{name}",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            pids = result.stdout.splitlines()
            for pid in pids:
                subprocess.run(["kill", "-9", pid], check=False)
            print(f"[+] Stream stopped for camera '{camera}'.")
        except FileNotFoundError as exc:
            raise RuntimeError("pgrep command not found. Please ensure it is installed and in your PATH.") from exc
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"pgrep failed with exit code {exc.returncode}: {exc.stderr}") from exc
        except Exception as exc:
            raise RuntimeError(f"An unexpected error occurred while stopping the stream: {exc}") from exc

    def is_chardev(self, p: str) -> bool:
        try:
            st = os.stat(p)
            return stat.S_ISCHR(st.st_mode)
        except FileNotFoundError:
            return False

    def find_video_devices(
        self,
        pixel_format: str = "H264",
        size: str = "640x480",
        device_glob: str = "/dev/video*",
        include_alias: bool = False,
    ) -> list[str]:
        """Find video devices that support the specified pixel format and size."""

        pix_re_a = re.compile(r"Pixel\s*Format\s*:\s*'([A-Z0-9]{4})'", re.I)
        pix_re_b = re.compile(r"^\s*\[\d+\]\s*:\s*'([A-Z0-9]{4})'", re.I | re.M)
        size_re = re.compile(rf"\b{re.escape(size)}\b", re.I)

        want = {pixel_format.upper()}
        if include_alias and pixel_format.upper() == "YUYV":
            want.add("YUY2")

        def device_supports(dev: str) -> bool:
            if not self.is_chardev(dev):
                return False
            try:
                out = subprocess.run(
                    ["v4l2-ctl", "-d", dev, "--list-formats-ext"],
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                ).stdout
            except Exception:
                return False
            if not out:
                return False

            current_code = None
            for line in out.splitlines():
                m = pix_re_a.search(line) or pix_re_b.search(line)
                if m:
                    current_code = m.group(1).upper()
                    continue
                if current_code in want and size_re.search(line):
                    return True
            return False

        return [dev for dev in sorted(glob.glob(device_glob)) if device_supports(dev)]
