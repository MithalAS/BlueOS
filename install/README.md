# Installation directory

This folder contains all necessary files for configuration of the host computer and installation of BlueOS.

To use it, just run the installation script in your terminal **as root**, like so:

```bash
sudo su -c 'curl -fsSL https://raw.githubusercontent.com/bluerobotics/BlueOS/master/install/install.sh | bash'
```

# Using different versions or custom builds
To use a different remote or version, you can se the following environment variables:
- `REMOTE`: Where the files are, E.g: https://raw.githubusercontent.com/patrickelectric/BlueOS-docker
- `VERSION`: Branch (If using GitHub) or folder (If using HTTP server) to be used.
- `KERNEL_REMOTE`: Kernel repository raw URL; defaults to `REMOTE`.
- `KERNEL_REF`: Kernel tag or branch; defaults to `VERSION`. Kernel downloads try `refs/tags` first, then `refs/heads`.

CI image builds set the kernel source independently of the script source. Pull request builds
use the PR's head repository and branch for kernel packages, while serving the checked-out
installation scripts locally.

## Boot configuration overrides

The custom file is optional and intended for development, troubleshooting, and
new hardware experiments, not production defaults. Its contents are your responsibility.

Installation and the Pi 4/Pi 5 startup patches append this footer to `config.txt`
if the custom-file reference is missing:

```ini
[all]
dtoverlay=
include blueos-custom.txt
```

An existing reference is left alone, not removed or moved. If you manually edit
`config.txt`, keep the footer last when you want custom settings to load last.

Put test settings in `blueos-custom.txt` on the boot partition: `/boot` on
Bullseye, or `/boot/firmware` on Bookworm. Installation creates an empty file
without overwriting an existing one. On an existing installation, create the
file yourself; an absent file supplies no overrides. Startup patches do not edit
its contents, and its settings load after the managed settings. The empty
`dtoverlay=` resets overlay parameter scope, so initial `dtparam` settings target
the base device tree. Use board filters and overlay-specific parameters as needed.
This file lives on the host, not inside the Docker image. Edit it directly (for
example, `sudo nano /boot/firmware/blueos-custom.txt` on Bookworm); no Docker image
rebuild or file synchronization is needed.

For example, to test a different Pi 4 I2C6 bus speed:

```ini
[pi4]
dtoverlay=i2c6,pins_22_23,baudrate=100000
```

Reboot to apply changes. Pi 4's XRM overlay is always loaded before the managed
I2C6 overlay because XRM also writes the bus's `clock-frequency`. The managed speed
is 400 kHz; the example above overrides it to 100 kHz. A last-loaded file ensures
ordering, not that arbitrary settings are safe or supported by an overlay.

The isolated kernel-selection and failure-path tests can be run with
`bash install/tests/test_kernel_install.sh`; they do not modify the host or install packages.

Remember that to do that, you need to set the environment variables as root:
```sh
sudo su
# You can also change the install URL to use a different source for files
curl -fsSL https://raw.githubusercontent.com/patrickelectric/BlueOS-Docker/example-version/install/install.sh | export REMOTE=https://raw.githubusercontent.com/patrickelectric/BlueOS-docker export VERSION=example-version bash
```