#!/usr/bin/env bash
set -e

VERSION="${VERSION:-master}"
GITHUB_REPOSITORY=${GITHUB_REPOSITORY:-bluerobotics/BlueOS}
REMOTE="${REMOTE:-https://raw.githubusercontent.com/${GITHUB_REPOSITORY}}"
ROOT="$REMOTE/$VERSION"
CONFIGURE_BOARD_PATH="$ROOT/install/boards"
alias curl="curl --retry 6 --max-time 15 --retry-all-errors --retry-delay 20 --connect-timeout 60"

function board_not_detected {
    echo "Hardware not identified in $1, please report back the following line:"
    echo "---"
    printf '%s' "$2" | gzip -c | base64 -w0
    echo
    echo "---"
}

echo "Detecting board type"

if [ -f "/proc/device-tree/model" ]; then
    CPU_MODEL=$(tr -d '\0' < /proc/device-tree/model)

    if [[ $CPU_MODEL =~ Raspberry\ Pi\ [0-3] ]]; then
        echo "Detected BCM28XX via device tree"
        curl -fsSL "$CONFIGURE_BOARD_PATH/bcm_28xx.sh" | bash

    elif [[ $CPU_MODEL =~ (Raspberry\ Pi\ 4)|(Raspberry\ Pi\ Compute\ Module\ 4.*) ]]; then
        echo "Detected BCM27XX via device tree"
        curl -fsSL "$CONFIGURE_BOARD_PATH/bcm_27xx.sh" | bash

    elif [[ $CPU_MODEL =~ (Raspberry\ Pi\ Compute\ Module\ 5.*)|(Compute\ Module\ 5.*) ]]; then
        echo "Detected Raspberry Pi Compute Module 5 via device tree"
        curl -fsSL "$CONFIGURE_BOARD_PATH/bcm_2712.sh" | bash

    elif [[ $CPU_MODEL =~ Raspberry\ Pi\ 5 ]]; then
        echo "Detected Raspberry Pi 5 via device tree"
        curl -fsSL "$CONFIGURE_BOARD_PATH/bcm_2712.sh" | bash

    else
        board_not_detected "/proc/device-tree/model" "$CPU_MODEL"
    fi

elif [ -f "/proc/cpuinfo" ]; then
    CPU_INFO="$(cat /proc/cpuinfo)"
    if [[ $CPU_INFO =~ BCM27[0-9]{2} ]]; then
        echo "Detected BCM27XX via cpuinfo"
        curl -fsSL "$CONFIGURE_BOARD_PATH/bcm_27xx.sh" | bash
    elif [[ $CPU_INFO =~ BCM28[0-9]{2} ]]; then
        echo "Detected BCM28XX via cpuinfo"
        curl -fsSL "$CONFIGURE_BOARD_PATH/bcm_28xx.sh" | bash
    else
        board_not_detected "/proc/cpuinfo" "$CPU_INFO"
    fi
else
    echo "Impossible to detect hardware, aborting."
    exit 255
fi
