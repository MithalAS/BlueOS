#!/usr/bin/env bash

set -e

# ----- config -----
VERSION="${VERSION:-v1.15.3}"   # set to "latest" for the newest release
REPO="bluenviron/mediamtx"
BIN_DIR="${BIN_DIR:-/usr/local/bin}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

echo "Installing MediaMTX ($REPO), version: $VERSION"

# map uname -m to mediamtx arch suffix
case "$(uname -m)" in
  x86_64|amd64)   ARCH=amd64  ;;
  aarch64|arm64)  ARCH=arm64  ;;
  armv7l|armv7|armhf) ARCH=armv7 ;;
  armv6l|armv6)   ARCH=armv6  ;;
  *) echo "Unsupported architecture: $(uname -m)"; exit 1 ;;
esac

# build URLs
if [[ "$VERSION" == "latest" ]]; then
  TARBALL="mediamtx_linux_${ARCH}.tar.gz"
  BASE_URL="https://github.com/${REPO}/releases/latest/download"
else
  TARBALL="mediamtx_${VERSION}_linux_${ARCH}.tar.gz"
  BASE_URL="https://github.com/${REPO}/releases/download/${VERSION}"
fi

echo "Arch: $ARCH"
echo "Downloading: ${BASE_URL}/${TARBALL}"
curl -fsSL "${BASE_URL}/${TARBALL}" -o "${TMP_DIR}/${TARBALL}"

# extract and install
tar -xzf "${TMP_DIR}/${TARBALL}" -C "${TMP_DIR}"
install -m 0755 "${TMP_DIR}/mediamtx" "${BIN_DIR}/mediamtx"

echo "Installed to ${BIN_DIR}/mediamtx"
echo -n "Version: "; "${BIN_DIR}/mediamtx" --version || true