#!/usr/bin/env bash

set -eu

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEST_DIR=$(mktemp -d)
mkdir "$TEST_DIR/status"
trap 'rm -f "$TEST_DIR/status/kernel_install_status.txt" "$TEST_DIR/output" "$TEST_DIR/trace"; rmdir "$TEST_DIR/status" "$TEST_DIR"' EXIT

run_case()
{
    : > "$TEST_DIR/trace"
    env HOME="$TEST_DIR/status" TRACE="$TEST_DIR/trace" \
        INSTALLER="$REPO_ROOT/install/install.sh" ARCHITECTURE="$1" \
        REMOTE="http://local" VERSION="master" \
        KERNEL_REMOTE="$2" KERNEL_REF="$3" DOWNLOAD_MODE="$4" \
        INSTALL_MODE="${5:-success}" SKIP_KERNEL_INSTALL="" \
        bash > "$TEST_DIR/output" 2>&1 <<'BASH'
set -e

wget()
{
    local url=${@: -1}
    printf 'download %s\n' "$url" >> "$TRACE"
    case "$DOWNLOAD_MODE" in
        tags) [[ "$url" == */refs/tags/* ]] ;;
        heads) [[ "$url" == */refs/heads/* ]] ;;
        failure) return 1 ;;
    esac
}

sudo()
{
    printf '%s ' "$@" >> "$TRACE"
    printf '\n' >> "$TRACE"
    if [[ "$INSTALL_MODE" == failure && "$1" == dpkg ]]; then
        return 1
    fi
    if [[ "$INSTALL_MODE" == overlay-failure && "$1" == cp ]]; then
        echo "Mock overlay copy failure" >&2
        return 1
    fi
    if [[ "$1" == tee ]]; then
        cat > /dev/null
    fi
    return 0
}

grep() { return 1; }

# Exercise the actual kernel block without running host configuration or reboot.
source <(sed -n '/^echo "Architecture: /,/^# Keep user experiments/{
    /^# Keep user experiments/!p
}' "$INSTALLER")
printf 'configured %s %s\n' "$CONFIG_TXT_PATH" "$KERNEL_LINE" >> "$TRACE"
BASH
}

assert_trace()
{
    if ! grep -qF "$1" "$TEST_DIR/trace"; then
        echo "Missing expected trace: $1" >&2
        cat "$TEST_DIR/trace" >&2
        exit 1
    fi
}

KERNEL_REMOTE=https://raw.githubusercontent.com/example/fork
PACKAGE=linux-image-5.10.110-rem-a892238df-v7l+_5.10.110-rem-a892238df-1_armhf.deb

for architecture in armv7 armv7l armhf; do
    run_case "$architecture" "$KERNEL_REMOTE" feature/kernel heads
    assert_trace "download $KERNEL_REMOTE/refs/tags/feature/kernel/$PACKAGE"
    assert_trace "download $KERNEL_REMOTE/refs/heads/feature/kernel/$PACKAGE"
    assert_trace "dpkg -i $PACKAGE"
    assert_trace "cp /usr/lib/linux-image-5.10.110-rem-a892238df-v7l+/overlays/xrm117x-i2c6.dtbo /boot/overlays/xrm117x-i2c6.dtbo"
    assert_trace "configured /boot/config.txt kernel=vmlinuz-5.10.110-rem-a892238df-v7l+"
done
echo "PASS: PR head branch and fork source install the armhf kernel for all armv7 aliases."

run_case armv7 "$KERNEL_REMOTE" 1.4.5 tags
assert_trace "download $KERNEL_REMOTE/refs/tags/1.4.5/$PACKAGE"
if grep -qF '/refs/heads/' "$TEST_DIR/trace"; then
    echo "Unexpected branch fallback after a successful tag download" >&2
    exit 1
fi
echo "PASS: successful tag downloads do not fall back to a branch."

run_case armv7 "" "" heads
assert_trace "download http://local/refs/heads/master/$PACKAGE"
echo "PASS: standalone installation retains REMOTE and VERSION defaults."

for mode in download-failure failure overlay-failure; do
    download_mode=heads
    install_mode=$mode
    if [[ "$mode" == download-failure ]]; then
        download_mode=failure
        install_mode=success
    fi
    if run_case armv7 "$KERNEL_REMOTE" feature/kernel "$download_mode" "$install_mode"; then
        echo "Expected a nonzero exit for $mode" >&2
        exit 1
    fi
    if grep -qF 'configured ' "$TEST_DIR/trace"; then
        echo "Kernel configuration continued after $mode" >&2
        exit 1
    fi
    case "$mode" in
        download-failure) grep -qF 'Failed to download kernel package' "$TEST_DIR/output" ;;
        failure) grep -qF 'Kernel package installation failed.' "$TEST_DIR/output" ;;
        overlay-failure) grep -qF 'Mock overlay copy failure' "$TEST_DIR/output" ;;
    esac
done
echo "PASS: armv7 download, package installation and overlay failures abort explicitly."

run_case aarch64 "$KERNEL_REMOTE" 1.4.5 tags
assert_trace "dpkg -i linux-image-5.10.110-rem-a892238df-v8+_5.10.110-rem-a892238df-1_arm64.deb"
assert_trace "configured /boot/firmware/config.txt kernel=vmlinuz-5.10.110-rem-a892238df-v8+"
echo "PASS: existing arm64 kernel selection and boot paths are unchanged."
