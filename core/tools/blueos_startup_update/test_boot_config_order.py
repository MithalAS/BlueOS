import subprocess
from pathlib import Path
from typing import Dict, List

import blueos_startup_update
import pytest
from commonwealth.utils.general import CpuType
from test_blueos_startup_update import (
    BOOKWORM,
    DISTRIBUTIONS,
    NAVIGATOR_BOARDS,
    NAVIGATOR_INSTALL_SCRIPTS,
    REPOSITORY_PATH,
    Distribution,
    apply_boot_config_patches,
    install_script_configuration,
    install_script_section,
    section_configuration,
    stock_files,
)


def apply_install_script_section(script_name: str, config_txt: str) -> str:
    """Run the insertion loop of the install script on a config.txt held in memory."""
    section_name = install_script_section(script_name)
    _, insertions = install_script_configuration(script_name)
    lines = config_txt.splitlines()
    if f"[{section_name}]" not in lines:
        lines.append(f"[{section_name}]")
    line_number = lines.index(f"[{section_name}]")
    for string in insertions:
        line_number += 1
        lines.insert(line_number, string)
    return "\n".join(lines) + "\n"


def assert_dtparam_lines_precede_overlays(section_lines: List[str]) -> None:
    seen_overlay = False
    for line in section_lines:
        if line == blueos_startup_update.BOOT_CONFIG_END_OVERLAY_SCOPE:
            seen_overlay = False
            continue
        if line.startswith("dtoverlay="):
            seen_overlay = True
            continue
        if line.startswith("dtparam=") and seen_overlay:
            raise AssertionError(f"dtparam line {line!r} appears after a dtoverlay line in {section_lines}")


SHIPPED_REVERSED_PI5_SECTION = """[pi5]
dtoverlay=dwc2,dr_mode=peripheral
gpio=37=op,pd,dl
gpio=11,24,25=op,pu,dh
dtoverlay=spi1-3cs
dtoverlay=spi0-led
dtparam=spi=on
dtoverlay=i2c-gpio,i2c_gpio_sda=22,i2c_gpio_scl=23,bus=6,i2c_gpio_delay_us=0
dtoverlay=i2c3-pi5.baudrate=400000
dtoverlay=i2c3-pi5,baudrate=400000
dtoverlay=i2c1
dtparam=i2c_arm=on
dtoverlay=uart2-pi5
dtoverlay=uart4-pi5
dtoverlay=uart3-pi5
dtoverlay=uart0-pi5
enable_uart=1
"""

USER_SECTION_LINES = [
    "dtparam=i2c_arm=on",
    "dtoverlay=my-custom-hat",
    "dtparam=spi=off #custom",
    "# plain user comment",
]


def user_section_fixture(distribution: Distribution, cpu_type: CpuType) -> Dict[str, str]:
    section_name = install_script_section(NAVIGATOR_INSTALL_SCRIPTS[cpu_type])
    files = stock_files(distribution)
    files[distribution.config_file] += f"\n[{section_name}]\n" + "\n".join(USER_SECTION_LINES) + "\n"
    return files


@pytest.mark.parametrize("distribution, cpu_type", NAVIGATOR_BOARDS)
def test_install_script_writes_declared_order(distribution: Distribution, cpu_type: CpuType) -> None:
    script_name = NAVIGATOR_INSTALL_SCRIPTS[cpu_type]
    section_name = install_script_section(script_name)
    _, insertions = install_script_configuration(script_name)

    installed_config = apply_install_script_section(script_name, distribution.stock_config)

    assert section_configuration(installed_config, section_name)[: len(insertions)] == insertions


@pytest.mark.parametrize("distribution, cpu_type", NAVIGATOR_BOARDS)
def test_install_script_and_startup_patches_agree(distribution: Distribution, cpu_type: CpuType) -> None:
    script_name = NAVIGATOR_INSTALL_SCRIPTS[cpu_type]
    section_name = install_script_section(script_name)

    installed_config = apply_install_script_section(script_name, distribution.stock_config)
    files = stock_files(distribution)
    apply_boot_config_patches(cpu_type, distribution, files)

    assert section_configuration(files[distribution.config_file], section_name) == section_configuration(
        installed_config, section_name
    )


@pytest.mark.parametrize("distribution", DISTRIBUTIONS)
def test_pi4_disables_bluetooth_and_loads_usb_overlay_once(distribution: Distribution) -> None:
    installed_config = apply_install_script_section(NAVIGATOR_INSTALL_SCRIPTS[CpuType.PI4], distribution.stock_config)
    files = stock_files(distribution)

    apply_boot_config_patches(CpuType.PI4, distribution, files)

    for config in (installed_config, files[distribution.config_file]):
        section_lines = section_configuration(config, "pi4")
        assert section_lines.count("dtoverlay=disable-bt") == 1
        assert section_lines.count("dtoverlay=dwc2,dr_mode=otg") == 1


@pytest.mark.parametrize("distribution, cpu_type", NAVIGATOR_BOARDS)
def test_board_section_keeps_dtparam_before_overlays(distribution: Distribution, cpu_type: CpuType) -> None:
    section_name = install_script_section(NAVIGATOR_INSTALL_SCRIPTS[cpu_type])
    files = stock_files(distribution)

    apply_boot_config_patches(cpu_type, distribution, files)

    assert_dtparam_lines_precede_overlays(section_configuration(files[distribution.config_file], section_name))


@pytest.mark.parametrize("distribution, cpu_type", NAVIGATOR_BOARDS)
def test_board_section_ends_the_overlay_scope(distribution: Distribution, cpu_type: CpuType) -> None:
    section_name = install_script_section(NAVIGATOR_INSTALL_SCRIPTS[cpu_type])
    files = stock_files(distribution)
    assert any(line.startswith("dtoverlay=") for line in distribution.stock_config.splitlines())

    apply_boot_config_patches(cpu_type, distribution, files)

    section_lines = section_configuration(files[distribution.config_file], section_name)
    first_dtparam = next(index for index, line in enumerate(section_lines) if line.startswith("dtparam="))
    assert section_lines.index(blueos_startup_update.BOOT_CONFIG_END_OVERLAY_SCOPE) < first_dtparam


@pytest.mark.parametrize("distribution, cpu_type", NAVIGATOR_BOARDS)
def test_board_section_keeps_the_hat_overlay_loadable(distribution: Distribution, cpu_type: CpuType) -> None:
    section_name = install_script_section(NAVIGATOR_INSTALL_SCRIPTS[cpu_type])
    files = stock_files(distribution)
    files[distribution.config_file] = "# a config.txt with no dtparam and no dtoverlay\n"

    apply_boot_config_patches(cpu_type, distribution, files)

    section_lines = section_configuration(files[distribution.config_file], section_name)
    assert blueos_startup_update.BOOT_CONFIG_END_OVERLAY_SCOPE not in section_lines
    assert_dtparam_lines_precede_overlays(section_lines)


@pytest.mark.parametrize("distribution, cpu_type", NAVIGATOR_BOARDS)
def test_board_section_keeps_the_scope_end_of_the_user(distribution: Distribution, cpu_type: CpuType) -> None:
    user_dtparam = "dtparam=act_led_trigger=heartbeat"
    files = stock_files(distribution)
    files[distribution.config_file] += f"\n{blueos_startup_update.BOOT_CONFIG_END_OVERLAY_SCOPE}\n{user_dtparam}\n"

    apply_boot_config_patches(cpu_type, distribution, files)

    patched_lines = files[distribution.config_file].splitlines()
    assert (
        patched_lines[patched_lines.index(user_dtparam) - 1] == blueos_startup_update.BOOT_CONFIG_END_OVERLAY_SCOPE
    ), "the patch removed the empty dtoverlay= that the user wrote"


def test_startup_patches_repair_a_reversed_board_section() -> None:
    _, insertions = install_script_configuration(NAVIGATOR_INSTALL_SCRIPTS[CpuType.PI5])
    files = stock_files(BOOKWORM)
    files[BOOKWORM.config_file] = BOOKWORM.stock_config + SHIPPED_REVERSED_PI5_SECTION

    applied = apply_boot_config_patches(CpuType.PI5, BOOKWORM, files)

    restarting = [name for name, wants_restart in applied.items() if wants_restart]
    assert restarting, "repairing a reversed section has to ask for a restart"
    assert section_configuration(files[BOOKWORM.config_file], "pi5")[: len(insertions)] == insertions
    assert_dtparam_lines_precede_overlays(section_configuration(files[BOOKWORM.config_file], "pi5"))


def test_startup_patches_converge_after_repairing_a_reversed_board_section() -> None:
    files = stock_files(BOOKWORM)
    files[BOOKWORM.config_file] = BOOKWORM.stock_config + SHIPPED_REVERSED_PI5_SECTION
    apply_boot_config_patches(CpuType.PI5, BOOKWORM, files)
    patched = dict(files)

    applied = apply_boot_config_patches(CpuType.PI5, BOOKWORM, files)

    restarting = [name for name, wants_restart in applied.items() if wants_restart]
    assert not restarting, f"{restarting} did not converge after repairing the reversed section"
    assert files == patched


@pytest.mark.parametrize("distribution, cpu_type", NAVIGATOR_BOARDS)
def test_board_section_rewrite_keeps_each_user_line_once(distribution: Distribution, cpu_type: CpuType) -> None:
    section_name = install_script_section(NAVIGATOR_INSTALL_SCRIPTS[cpu_type])
    files = user_section_fixture(distribution, cpu_type)

    apply_boot_config_patches(cpu_type, distribution, files)

    section_lines = section_configuration(files[distribution.config_file], section_name)
    for user_line in USER_SECTION_LINES:
        assert section_lines.count(user_line) == 1, f"{user_line!r} appeared {section_lines.count(user_line)} times"


@pytest.mark.parametrize("distribution, cpu_type", NAVIGATOR_BOARDS)
def test_board_section_rewrite_converges_with_user_lines(distribution: Distribution, cpu_type: CpuType) -> None:
    files = user_section_fixture(distribution, cpu_type)

    apply_boot_config_patches(cpu_type, distribution, files)
    patched = dict(files)

    for run in (2, 3):
        applied = apply_boot_config_patches(cpu_type, distribution, files)
        restarting = [name for name, wants_restart in applied.items() if wants_restart]
        assert not restarting, f"run {run} requested restart for {restarting}"
        assert files == patched, f"run {run} changed the boot files"


@pytest.mark.parametrize("distribution, cpu_type", NAVIGATOR_BOARDS)
def test_board_section_rewrite_drops_a_protected_line(distribution: Distribution, cpu_type: CpuType) -> None:
    section_name = install_script_section(NAVIGATOR_INSTALL_SCRIPTS[cpu_type])
    protected_spi = "dtparam=spi=off #custom"
    files = stock_files(distribution)
    files[distribution.config_file] += f"\n[{section_name}]\n{protected_spi}\n"

    apply_boot_config_patches(cpu_type, distribution, files)

    section_lines = section_configuration(files[distribution.config_file], section_name)
    assert section_lines.count(protected_spi) == 1
    assert section_lines.count("dtparam=spi=on") == 0


@pytest.mark.parametrize("distribution, cpu_type", NAVIGATOR_BOARDS)
def test_board_section_rewrite_keeps_a_protected_line_and_a_plain_one(
    distribution: Distribution, cpu_type: CpuType
) -> None:
    section_name = install_script_section(NAVIGATOR_INSTALL_SCRIPTS[cpu_type])
    protected = "dtoverlay=i2c1 # custom"
    user_line = "hdmi_force_hotplug=1"
    files = stock_files(distribution)
    files[distribution.config_file] += f"\n[{section_name}]\n{protected}\n{user_line}\n"

    apply_boot_config_patches(cpu_type, distribution, files)

    section_lines = section_configuration(files[distribution.config_file], section_name)
    assert section_lines.count(protected) == 1
    assert section_lines.count(user_line) == 1


@pytest.mark.parametrize("distribution", DISTRIBUTIONS)
def test_pi4_always_loads_xrm_before_i2c6_and_converges(distribution: Distribution) -> None:
    files = stock_files(distribution)

    applied = apply_boot_config_patches(CpuType.PI4, distribution, files)

    xrm = "dtoverlay=xrm117x-i2c6"
    lines = files[distribution.config_file].splitlines()
    assert lines.count(xrm) == 1
    section_lines = section_configuration(files[distribution.config_file], "pi4")
    assert section_lines.index(xrm) < section_lines.index("dtoverlay=i2c6,pins_22_23,baudrate=100000")
    assert any(applied.values())
    patched = dict(files)
    assert not any(apply_boot_config_patches(CpuType.PI4, distribution, files).values())
    assert files == patched


@pytest.mark.parametrize("distribution, cpu_type", NAVIGATOR_BOARDS)
@pytest.mark.parametrize("stock_config", [True, False], ids=["stock-config", "minimal-config"])
def test_custom_include_is_last_and_its_contents_are_not_managed(
    distribution: Distribution, cpu_type: CpuType, stock_config: bool
) -> None:
    files = stock_files(distribution)
    if not stock_config:
        files[distribution.config_file] = ""
    include = blueos_startup_update.BOOT_CONFIG_CUSTOM_INCLUDE
    custom_path = str(Path(distribution.config_file).with_name("blueos-custom.txt"))
    custom_content = "[pi4]\ndtoverlay=i2c6,pins_22_23,baudrate=100000\n"
    files[custom_path] = custom_content

    apply_boot_config_patches(cpu_type, distribution, files)

    lines = files[distribution.config_file].splitlines()
    assert lines[-3:] == blueos_startup_update.BOOT_CONFIG_CUSTOM_FOOTER
    assert lines.count(include) == 1
    assert files[custom_path] == custom_content
    patched = dict(files)
    assert not any(apply_boot_config_patches(cpu_type, distribution, files).values())
    assert files == patched

    # Editing the host file after deployment must not require changes to the image or managed config.
    files[custom_path] = custom_content.replace("baudrate=100000", "baudrate=200000")
    edited = dict(files)
    assert not any(apply_boot_config_patches(cpu_type, distribution, files).values())
    assert files == edited


@pytest.mark.parametrize("distribution", DISTRIBUTIONS)
def test_pi4_board_installer_moves_xrm_before_i2c6(distribution: Distribution, tmp_path: Path) -> None:
    content = (REPOSITORY_PATH / NAVIGATOR_INSTALL_SCRIPTS[CpuType.PI4]).read_text(encoding="utf-8")
    board_config = content.split("# Remove any configuration related to i2c", 1)[1].split(
        "# Check for valid modules", 1
    )[0]
    board_config = "# Remove any configuration related to i2c" + board_config
    config_file = tmp_path / "config.txt"
    config_file.write_text(distribution.stock_config + "\n[all]\ndtoverlay=xrm117x-i2c6,addr=0x30\n", encoding="utf-8")

    subprocess.run(
        ["bash", "-c", f'set -e\nsudo() {{ "$@"; }}\nCONFIG_FILE="{config_file}"\n{board_config}'],
        check=True,
        capture_output=True,
        text=True,
    )

    config = config_file.read_text(encoding="utf-8")
    xrm = "dtoverlay=xrm117x-i2c6"
    assert config.splitlines().count(xrm) == 1
    lines = section_configuration(config, "pi4")
    assert lines.index(xrm) < lines.index("dtoverlay=i2c6,pins_22_23,baudrate=100000")


@pytest.mark.parametrize("distribution", DISTRIBUTIONS)
def test_kernel_installer_keeps_xrm_before_i2c6_and_custom_include_last(
    distribution: Distribution, tmp_path: Path
) -> None:
    content = (REPOSITORY_PATH / "install/install.sh").read_text(encoding="utf-8")
    kernel_config = (
        'echo "Architecture: '
        + content.split('echo "Architecture: ', 1)[1].split('echo "Installation finished successfully."', 1)[0]
    )
    kernel_config = kernel_config.replace("/boot", f"{tmp_path}/boot")
    boot_path = tmp_path / distribution.config_file.lstrip("/")
    boot_path.parent.mkdir(parents=True)
    installed = apply_install_script_section(NAVIGATOR_INSTALL_SCRIPTS[CpuType.PI4], distribution.stock_config)
    xrm = "dtoverlay=xrm117x-i2c6"
    boot_path.write_text(installed, encoding="utf-8")
    custom_file = boot_path.with_name("blueos-custom.txt")
    custom_file.write_text("[pi4]\ndtparam=i2c_arm_baudrate=100000\n", encoding="utf-8")
    custom_content = custom_file.read_text(encoding="utf-8")
    architecture = "armv7l" if distribution.name == "bullseye" else "aarch64"
    script = f"""
set -e
HOME="{tmp_path}"
ARCHITECTURE={architecture}
REMOTE=http://local
VERSION=master
SKIP_KERNEL_INSTALL=""
wget() {{ return 0; }}
sudo() {{
    case "$1" in
        dpkg|cp) return 0 ;;
        *) "$@" ;;
    esac
}}
{kernel_config}
"""
    for _ in range(2):
        subprocess.run(["bash", "-c", script], check=True, capture_output=True, text=True)
        config = boot_path.read_text(encoding="utf-8")
        lines = section_configuration(config, "pi4")
        assert lines.count(xrm) == 1
        assert lines.index(xrm) < lines.index("dtoverlay=i2c6,pins_22_23,baudrate=100000")
        assert config.splitlines()[-3:] == blueos_startup_update.BOOT_CONFIG_CUSTOM_FOOTER
        assert config.splitlines().count(blueos_startup_update.BOOT_CONFIG_CUSTOM_INCLUDE) == 1
        assert custom_file.read_text(encoding="utf-8") == custom_content


def test_ensuring_custom_include_leaves_an_existing_reference_untouched() -> None:
    lines = ["[pi4]", "dtoverlay=uart1", "", *blueos_startup_update.BOOT_CONFIG_CUSTOM_FOOTER, "dtparam=audio=on"]
    original = lines.copy()

    blueos_startup_update.boot_config_ensure_custom_include(lines)

    assert lines == original
