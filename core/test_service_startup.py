import re
import shlex
import subprocess
from pathlib import Path

import pytest

CORE_PATH = Path(__file__).parent


@pytest.mark.parametrize("service", ["vescConfigEditor", "remoraCameraManager", "modbus"])
def test_service_starts_as_blueos_with_runtime_environment(service: str) -> None:
    startup = (CORE_PATH / "start-blueos-core").read_text(encoding="utf-8")
    assignments = []
    for name in (
        "BLUEOS_PATH",
        "SERVICES_PATH",
        "RUN_AS_REGULAR_USER_BEGIN",
        "RUN_AS_REGULAR_USER_END",
    ):
        assignment = re.search(rf"^{name}=.*$", startup, re.MULTILINE)
        assert assignment is not None
        assignments.append(assignment.group(0))
    service_entry = re.search(rf"^\s+'{service}',.*$", startup, re.MULTILINE)
    assert service_entry is not None
    services = f"SERVICES=(\n{service_entry.group(0)}\n)"
    # Expand only declarations, without executing the container's boot-time operations.
    script = "\n".join(["set -u", *assignments, services, 'printf "%s\\n" "${SERVICES[@]}"'])
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True)
    entry = next(line for line in result.stdout.splitlines() if line.startswith(f"{service},"))
    name, memory_limit, command = entry.split(",", 2)

    assert name == service
    assert memory_limit == "0"
    assert shlex.split(command) == [
        "nice",
        "-19",
        "sudo",
        "-u",
        "blueos",
        "bash",
        "-c",
        f"source /etc/blueosrc &&  /home/pi/services/{service}/main.py ",
    ]
