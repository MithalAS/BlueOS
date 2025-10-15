import os
import subprocess
import usbPortControl
import shutil
import glob
import re
import stat
from pathlib import Path
from typing import List

CONFIG_PATH = Path(".cameraManager.json")

default_config = {
    "PORT": 8554,
    "IP": "0.0.0.0",
    "USE_HW_ENC": False,
    "USB_HUB": "1-1",
    "FRONT": {
        "USB_HUB_PORT": 2,
        "device": "/dev/video4",
        "resolution": "640x480",
        "fps": 25,
        "name": "front",
        "kbitrate": 1000,
        "preset": "superfast",
    },
    "BACK": {
        "USB_HUB_PORT": 1,
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

    def __init__(self):
        self.config = default_config
        self.load_config()
        self.usbControl = usbPortControl.Uhubctl(use_sudo=False)

    def load_config(self) -> None:
        """Load the camera configuration."""
        if not CONFIG_PATH.exists():
            self.save_config()
        else:
            with open(CONFIG_PATH, "r") as f:
                import json

                self.config = json.load(f)

    def save_config(self) -> None:
        """Save the camera configuration."""
        with open(CONFIG_PATH, "w") as f:
            import json

            json.dump(self.config, f, indent=4)
            print(f"[+] Config saved to: {CONFIG_PATH}")

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
            result = subprocess.run(["uhubctl"], capture_output=True, text=True)
            if result.returncode != 0:
                raise Exception(f"uhubctl command failed with error: {result.stderr}")
            return result.stdout.splitlines()
        except FileNotFoundError:
            raise Exception("uhubctl command not found. Please ensure it is installed and in your PATH.")
        except Exception as e:
            raise Exception(f"An error occurred while running uhubctl: {e}")

    def set_config(self, new_config: dict) -> None:
        """Set a new configuration and save it."""
        self.config = new_config
        self.save_config()

    def power_cycle_camera(self, camera: str) -> None:
        """Power cycle the specified camera."""
        if camera not in self.config:
            raise ValueError(f"Camera '{camera}' not found in configuration.")

        cam_config = self.config[camera]
        port = cam_config.get("USB_HUB_PORT")
        location = self.config.get("USB_HUB")
        duration = 10  # seconds

        if port is None:
            raise ValueError(f"USB_HUB_PORT not defined for camera '{camera}'.")

        self.usbControl.power_cycle(location, port, duration)

    def start_mediamtx_server(self) -> None:
        """Start the media server process."""
        if shutil.which("docker"):
            subprocess.Popen(
                [
                    "docker",
                    "run",
                    "-d",
                    "--rm",
                    "--name",
                    "mediamtx",
                    "-p",
                    f"{self.config['IP']}:{self.config['PORT']}:{self.config['PORT']}",
                    "-v",
                    "/home/pi/mediamtx.yml:/mediamtx.yml:ro",
                    "bluenet/mediamtx:latest",
                    "-f",
                    "/mediamtx.yml",
                ]
            )
        else:
            raise EnvironmentError("Docker is not installed or not found in PATH.")

    def stop_media_server(self) -> None:
        """Stop the media server process."""
        if shutil.which("docker"):
            subprocess.run(["docker", "stop", "mediamtx"], check=False)
        else:
            raise EnvironmentError("Docker is not installed or not found in PATH.")

    def ffmpeg_cmd(self, device, res, fps, name, kbitrate, use_hw=True, preset="ultrafast") -> list[str]:
        input_format = "yuyv422"
        bitrate = f"{kbitrate}k"

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
        if camera not in self.config:
            raise ValueError(f"Camera '{camera}' not found in configuration.")

        cam_config = self.config[camera]
        device = cam_config.get("device")
        res = cam_config.get("resolution")
        fps = cam_config.get("fps")
        name = cam_config.get("name")
        kbitrate = cam_config.get("kbitrate")
        preset = cam_config.get("preset")
        use_hw = self.config.get("USE_HW_ENC")

        if device is None:
            raise ValueError(f"Device not defined for camera '{camera}'.")

        cmd = self.ffmpeg_cmd(device, res, fps, name, kbitrate, use_hw, preset)

        # RTSP output
        rtsp_url = f"rtsp://{self.config['IP']}:{self.config['PORT']}/{name}"
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
        subprocess.Popen(cmd)
        print(f"[+] Stream started for camera '{camera}'.")

    def stop_stream(self, camera: str) -> None:
        """Stop streaming for the specified camera."""
        if camera not in self.config:
            raise ValueError(f"Camera '{camera}' not found in configuration.")

        cam_config = self.config[camera]
        name = cam_config.get("name")

        if name is None:
            raise ValueError(f"Name not defined for camera '{camera}'.")

        # Find and kill the ffmpeg process streaming this camera
        try:
            result = subprocess.run(
                ["pgrep", "-f", f"rtsp://{self.config['IP']}:{self.config['PORT']}/{name}"],
                capture_output=True,
                text=True,
            )
            pids = result.stdout.splitlines()
            for pid in pids:
                subprocess.run(["kill", "-9", pid], check=False)
            print(f"[+] Stream stopped for camera '{camera}'.")
        except Exception as e:
            raise Exception(f"An error occurred while stopping the stream: {e}")

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

        matches: List[str] = []

        for dev in sorted(glob.glob(device_glob)):
            if not self.is_chardev(dev):
                continue

            try:
                out = subprocess.run(
                    ["v4l2-ctl", "-d", dev, "--list-formats-ext"],
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                ).stdout
            except Exception:
                continue

            if not out:
                continue

            lines = out.splitlines()
            current_code = None
            in_wanted_block = False
            found_size_in_block = False

            for line in lines:
                m = pix_re_a.search(line) or pix_re_b.search(line)
                if m:
                    current_code = m.group(1).upper()
                    in_wanted_block = current_code in want
                    found_size_in_block = False
                    continue

                if in_wanted_block:
                    if size_re.search(line):
                        found_size_in_block = True
                    if found_size_in_block:
                        matches.append(dev)
                        break

        return matches
