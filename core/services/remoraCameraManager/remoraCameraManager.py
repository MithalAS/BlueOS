import glob
import json
import logging
import os
import re
import select
import shutil
import stat
import subprocess
import textwrap
from pathlib import Path
from time import sleep, time
from typing import Any, Dict

from commonwealth.settings.manager import Manager
from pykson import Pykson

import usbPortControl
from settings import CameraConfig, SettingsV1

SERVICE_NAME = "remoraCameraManager"

USERDATA = Path("/usr/blueos/userdata/")

pyk = Pykson()
default_config: Dict[str, Any] = {
    "PORT": 8554,
    "IP": "127.0.0.1",
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

    def _config_path(self) -> Path:
        home = Path(os.environ.get("HOME", "/home/blueos"))
        return home / ".config" / "mediamtx" / "mediamtx.yml"

    def _ensure_config(self) -> Path:
        cfg = self._config_path()
        cfg.parent.mkdir(parents=True, exist_ok=True)

        port = int(self.settings_manager.settings.camera.PORT)
        default_cfg = textwrap.dedent(
            f"""\
            # Auto-generated MediaMTX configuration
            logLevel: info
            rtsp: yes
            rtspAddress: :{port}
            rtmp: no
            hls: no
            paths:
                all:
                    overridePublisher: yes
        """
        )

        # always overwrite for now
        cfg.write_text(default_cfg, encoding="utf-8")
        os.chmod(cfg, 0o644)

        return cfg

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

    def update_usb_permissions(self) -> bool:
        rule_path = Path("/etc/udev/rules.d/52-usb.rules")
        desired_rules = [
            # Consider using the official uhubctl recommendations, or adjust matching here.
            'SUBSYSTEM=="usb", DRIVER=="hub|usb", MODE="0666", ATTR{idVendor}=="32e4"',
            'SUBSYSTEM=="usb", DRIVER=="hub|usb", MODE="0666", ATTR{idVendor}=="2109"',
            'SUBSYSTEM=="usb", DRIVER=="hub|usb", MODE="0666", ATTR{idVendor}=="1d6b"',
        ]

        logging.info("Updating USB permissions at %s", str(rule_path))
        changed = False

        try:
            rule_path.parent.mkdir(parents=True, exist_ok=True)

            if not rule_path.exists():
                logging.info("Rules file does not exist, creating it.")
                rule_path.write_text("\n".join(desired_rules) + "\n", encoding="utf-8")
                changed = True
            else:
                existing = rule_path.read_text(encoding="utf-8").splitlines()
                with rule_path.open("a", encoding="utf-8") as f:
                    for line in desired_rules:
                        if line not in existing:
                            logging.info("Appending missing rule: %s", line)
                            f.write(line + "\n")
                            changed = True

            if changed:
                self.usbControl._run("sudo udevadm control --reload-rules", False)
                self.usbControl._run("sudo udevadm trigger --subsystem-match=usb", False)
                logging.info("udev rules reloaded and triggered.")
            else:
                logging.info("No changes needed; rules already present.")

            return changed

        except Exception as e:
            logging.exception("Failed to update USB permissions: %s", e)
            return False

    def get_uhubctrl_printout(self) -> list[str]:
        """Return the output of the uhubctl command."""
        try:
            result = subprocess.run(["uhubctl"], capture_output=True, text=True, check=True)
            return result.stdout.splitlines()
        except FileNotFoundError as exc:
            raise RuntimeError("uhubctl command not found. Please ensure it is installed and in your PATH.") from exc
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"uhubctl command failed with exit code {exc.returncode}: {exc.stderr}") from exc

    def list_video_port_formats(self, port: str) -> list[str]:
        """List supported formats for a given video port using v4l2-ctl."""
        try:
            result = subprocess.run(
                ["v4l2-ctl", "-d", port, "--list-formats-ext"],
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.splitlines()
        except FileNotFoundError as exc:
            raise RuntimeError("v4l2-ctl command not found. Please ensure it is installed and in your PATH.") from exc
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"v4l2-ctl command failed with exit code {exc.returncode}: {exc.stderr}") from exc

    def power_cycle_camera(self, cam: str) -> str:
        """Power cycle the specified camera."""
        if cam == "front":
            port = self.settings_manager.settings.camera.FRONT.usb_hub_port
        elif cam == "back":
            port = self.settings_manager.settings.camera.BACK.usb_hub_port
        else:
            raise ValueError(f"Unknown camera '{cam}'. Valid options are 'front' or 'back'.")

        if port is None:
            raise ValueError(f"usb_hub_port not defined for camera '{cam}'.")
        location = self.settings_manager.settings.camera.USB_HUB
        self.usbControl.power_cycle(location=location, port=port, off_seconds=10.0)  # power cycle for 10 seconds
        return f"Camera '{cam}' power cycled on hub {location} port {port} for 10 seconds."

    def start_mediamtx_server(self) -> str:
        mediamtx = shutil.which("mediamtx")
        if not mediamtx:
            raise EnvironmentError("MediaMTX binary not found in PATH.")

        cfg = self._ensure_config()

        try:
            # pylint: disable=consider-using-with
            proc = subprocess.Popen(
                [mediamtx, str(cfg)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                start_new_session=True,
                text=True,
            )
        except Exception as e:
            raise RuntimeError(f"Failed to start MediaMTX server: {e}") from e

        # read a few lines without blocking
        lines: list[str] = []
        deadline = time() + 2.0  # ~2s window
        max_lines = 5
        while time() < deadline and len(lines) < max_lines:
            if proc.poll() is not None:  # crashed
                remaining = proc.stdout.read() if proc.stdout else ""
                if remaining:
                    lines.extend(remaining.splitlines())
                raise RuntimeError("MediaMTX exited during startup:\n" + "\n".join(lines))
            if proc.stdout:
                r, _, _ = select.select([proc.stdout], [], [], 0.2)
                if r:
                    line = proc.stdout.readline()
                    if not line:
                        break
                    lines.append(line.rstrip())
        # return something useful even if it was quiet
        if not lines:
            return f"MediaMTX started (PID {proc.pid}) using {cfg}"
        return "\n".join(lines[-12:])  # last few startup lines

    def stop_mediamtx_server(self) -> str:
        """
        Stop the MediaMTX server if it's running.
        Returns a message indicating the result.
        """
        try:
            result = subprocess.run(
                ["pgrep", "-f", "mediamtx"],
                capture_output=True,
                text=True,
                check=True,
            )
            pids = result.stdout.splitlines()
            if not pids:
                return "MediaMTX server is not running."
            for pid in pids:
                subprocess.run(["kill", "-9", pid], check=False)
            return "MediaMTX server stopped."
        except FileNotFoundError as exc:
            raise RuntimeError("pgrep command not found. Please ensure it is installed and in your PATH.") from exc

    def check_mediamtx_running(self) -> bool:
        """Check if the MediaMTX server is currently running."""
        try:
            result = subprocess.run(
                ["pgrep", "-f", "mediamtx"],
                capture_output=True,
                text=True,
                check=True,
            )
            pids = result.stdout.splitlines()
            return len(pids) > 0
        except FileNotFoundError as exc:
            raise RuntimeError("pgrep command not found. Please ensure it is installed and in your PATH.") from exc
        except subprocess.CalledProcessError:
            return False

    def ffmpeg_cmd(self, cam_config: Any, use_hw: bool) -> list[str]:
        device = cam_config.device
        res = cam_config.resolution
        fps = cam_config.fps
        kbitrate = cam_config.kbitrate
        preset = cam_config.preset
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

    def start_stream(self, camera: str) -> str:
        """Start streaming for the specified camera."""
        if camera == "front":
            cam_config = self.settings_manager.settings.camera.FRONT
        elif camera == "back":
            cam_config = self.settings_manager.settings.camera.BACK
        else:
            raise ValueError(f"Camera '{camera}' not found in configuration.")

        device = cam_config.device
        use_hw = self.settings_manager.settings.camera.USE_HW_ENC

        if device is None:
            raise ValueError(f"Device not defined for camera '{camera}'.")

        cmd = self.ffmpeg_cmd(cam_config, bool(use_hw))

        if self.check_mediamtx_running() is False:
            print("MediaMTX server is not running. Might cause streaming issues.")

        # RTSP output
        rtsp_url = f"rtsp://{self.settings_manager.settings.camera.IP}:{self.settings_manager.settings.camera.PORT}/{cam_config.name}"
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
        # pylint: disable=consider-using-with
        proc = subprocess.Popen(cmd)
        sleep(1.0)  # give it a moment to start

        if proc.poll() is not None:
            raise RuntimeError(f"ffmpeg process for camera '{camera}' exited prematurely.")

        return f"Stream started successfully for camera '{camera}' with PID {proc.pid}."

    def stop_stream(self, camera: str) -> None:
        """Stop streaming for the specified camera."""
        if camera == "front":
            cam_config = self.settings_manager.settings.camera.FRONT
        elif camera == "back":
            cam_config = self.settings_manager.settings.camera.BACK
        else:
            raise ValueError(f"Camera '{camera}' not found in configuration.")

        name = cam_config.name

        if name is None:
            raise ValueError(f"Name not defined for camera '{camera}'.")

        # Find and kill the ffmpeg process streaming this camera
        try:
            result = subprocess.run(
                [
                    "pgrep",
                    "-f",
                    f"rtsp://{self.settings_manager.settings.camera.IP}:{self.settings_manager.settings.camera.PORT}/{name}",
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

    def kill_all_streams(self) -> None:
        """Kill all ffmpeg streaming processes."""
        try:
            result = subprocess.run(
                [
                    "pgrep",
                    "-f",
                    "ffmpeg",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            pids = result.stdout.splitlines()
            for pid in pids:
                subprocess.run(["kill", "-9", pid], check=False)
            print("All ffmpeg streams stopped.")
        except FileNotFoundError as exc:
            raise RuntimeError("pgrep command not found. Please ensure it is installed and in your PATH.") from exc
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"pgrep failed with exit code {exc.returncode}: {exc.stderr}") from exc
        except Exception as exc:
            raise RuntimeError(f"An unexpected error occurred while stopping all streams: {exc}") from exc

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
