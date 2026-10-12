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

The isolated kernel-selection and failure-path tests can be run with
`bash install/tests/test_kernel_install.sh`; they do not modify the host or install packages.

Remember that to do that, you need to set the environment variables as root:
```sh
sudo su
# You can also change the install URL to use a different source for files
curl -fsSL https://raw.githubusercontent.com/patrickelectric/BlueOS-Docker/example-version/install/install.sh | export REMOTE=https://raw.githubusercontent.com/patrickelectric/BlueOS-docker export VERSION=example-version bash
```