#!/usr/bin/env bash
set -e

VERSION="${VERSION:-master}"
GITHUB_REPOSITORY=${GITHUB_REPOSITORY:-bluerobotics/BlueOS}
REMOTE="${REMOTE:-https://raw.githubusercontent.com/${GITHUB_REPOSITORY}}"
ROOT="$REMOTE/$VERSION"

CMDLINE_FILE=/boot/firmware/cmdline.txt
CONFIG_FILE=/boot/firmware/config.txt

alias curl="curl --retry 6 --max-time 15 --retry-all-errors --retry-delay 20 --connect-timeout 60"

MODEL="$(tr -d '\0' </proc/device-tree/model 2>/dev/null || echo unknown)"
echo "Detected model: $MODEL"

SECTION_TAG="[pi5]"
if echo "$MODEL" | grep -qi "Compute Module 5"; then
  SECTION_TAG="[cm5]"
fi
echo "Using config section: $SECTION_TAG"

# Choose correct overlays directory
OVERLAYS_DIR="/boot/firmware/overlays"
if [ ! -d "$OVERLAYS_DIR" ]; then
  OVERLAYS_DIR="/boot/overlays"
fi
echo "Overlays directory: $OVERLAYS_DIR"

echo "Configuring BCM2712 board.."

# Download, compile, and install spi0 mosi-only device tree overlay for neopixel LED
echo "- compile spi0 device tree overlay."
DTS_PATH="$ROOT/install/overlays"
DTS_NAME="spi0-led"
curl -fsSL -o "/tmp/$DTS_NAME.dts" "$DTS_PATH/$DTS_NAME.dts"
dtc -@ -Hepapr -I dts -O dtb -o "$OVERLAYS_DIR/$DTS_NAME.dtbo" "/tmp/$DTS_NAME.dts"

# Remove any configuration related to i2c and spi/spi1 and do the necessary changes for navigator
echo "- Enable I2C, SPI and UART (config.txt)."
for STRING in \
  "enable_uart=" \
  "dtoverlay=uart" \
  "dtparam=i2c" \
  "dtoverlay=i2c" \
  "dtparam=spi=" \
  "dtoverlay=spi" \
  "gpio=" \
  "dwc2" \
  ; do
  sudo sed -i "/$STRING/d" "$CONFIG_FILE"
done

# Add section tag if not present
if ! grep -q "^$SECTION_TAG$" "$CONFIG_FILE"; then
  echo "$SECTION_TAG" | sudo tee -a "$CONFIG_FILE" >/dev/null
fi

line_number=$(grep -n "^$SECTION_TAG$" "$CONFIG_FILE" | head -n1 | awk -F ":" '{print $1}')
echo "Line number of $SECTION_TAG tag: $line_number"

# Insert required lines under the section tag
# (Removed duplicate: dtoverlay=i2c3-pi5.baudrate=400000)
for STRING in \
  "enable_uart=1" \
  "dtoverlay=uart0-pi5" \
  "dtoverlay=uart3-pi5" \
  "dtoverlay=uart4-pi5" \
  "dtoverlay=uart2-pi5" \
  "dtparam=i2c_arm=on" \
  "dtoverlay=i2c1" \
  "dtoverlay=i2c3-pi5,baudrate=400000" \
  "dtoverlay=i2c-gpio,i2c_gpio_sda=22,i2c_gpio_scl=23,bus=6,i2c_gpio_delay_us=0" \
  "dtparam=spi=on" \
  "dtoverlay=spi0-led" \
  "dtoverlay=spi1-3cs" \
  "gpio=11,24,25=op,pu,dh" \
  "gpio=37=op,pd,dl" \
  "dtoverlay=dwc2,dr_mode=otg" \
  ; do
  sudo sed -i "$line_number r /dev/stdin" "$CONFIG_FILE" <<< "$STRING"
done

# -------- keep your original module/cmdline logic below --------

# Check for valid modules file to load kernel modules
if [ -f "/etc/modules" ]; then
  MODULES_FILE="/etc/modules"
else
  MODULES_FILE="/etc/modules-load.d/blueos.conf"
  sudo touch "$MODULES_FILE" || true
fi

echo "- Set up kernel modules."
for STRING in "bcm2835-v4l2" "i2c-bcm2835" "i2c-dev"; do
  sudo sed -i "/$STRING/d" "$MODULES_FILE"
  echo "$STRING" | sudo tee -a "$MODULES_FILE" >/dev/null
done

# Remove any console serial configuration
echo "- Configure serial."
sudo sed -e 's/console=serial[0-9],[0-9]*\ //' -i "$CMDLINE_FILE"

# Set cgroup, necessary for docker access to memory information
echo "- Enable cgroup with memory and cpu"
grep -q cgroup "$CMDLINE_FILE" || (
  sudo sed -i '1 s/$/ cgroup_enable=cpuset cgroup_memory=1 cgroup_enable=memory/' "$CMDLINE_FILE"
)

echo "- Enable USB OTG as ethernet adapter"
grep -q dwc2 "$CMDLINE_FILE" || (
  sudo sed -i '1 s/$/ modules-load=dwc2,g_ether/' "$CMDLINE_FILE"
)
