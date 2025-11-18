import shlex
import subprocess
import time


class Uhubctl:
    """
    A simple wrapper around the uhubctl command-line tool to manage USB hub ports.
    """

    def __init__(self, use_sudo: bool = False):
        """
        Initialize the uhubctl interface.
          use_sudo: if True, commands are prefixed with 'sudo'.
        """
        self.use_sudo = use_sudo

    def _run(self, cmd: str, check: bool = True) -> str:
        """Run a shell command and return stdout as text."""
        try:
            res = subprocess.run(
                shlex.split(cmd),
                capture_output=True,
                text=True,
                check=check,
            )
            return res.stdout.strip()
        except FileNotFoundError as e:
            raise RuntimeError(f"Command not found: {cmd}. Is uhubctl installed and in your PATH?") from e
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Command failed ({cmd})\nstdout:\n{e.stdout}\nstderr:\n{e.stderr}") from e

    def list_hubs(self) -> str:
        """
        Returns the raw uhubctl listing (useful to find hub 'location' and ports).
        Equivalent to `uhubctl` with no args.
        """
        prefix = "sudo " if self.use_sudo else ""
        return self._run(f"{prefix}uhubctl")

    def port_power(self, location: str, port: int, on: bool) -> str:
        """
        Turn a single port on/off.
          location: hub path like '1-1' or '2-1.3'
          port: port number on that hub (int)
          on: True to power on, False to power off
        """
        action = 1 if on else 0
        prefix = "sudo " if self.use_sudo else ""
        cmd = f"{prefix}uhubctl -l {location} -p {port} -a {action}"
        return self._run(cmd)

    def power_cycle(self, location: str, port: int, off_seconds: float = 2.0) -> dict[str, str]:
        """
        Power-cycle a port by turning it off, waiting, then on.
        """
        off_out = self.port_power(location, port, on=False)

        time.sleep(off_seconds)

        on_out = self.port_power(location, port, on=True)

        return {"off_output": off_out, "on_output": on_out}
