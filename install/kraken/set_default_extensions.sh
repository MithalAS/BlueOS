#!/usr/bin/env bash

# Extensions data fetch, use for Extensions that are synced by some online source

COCKPIT_RELEASE_URL="https://api.github.com/repos/goasChris/cockpit/releases"

alias curl="curl --retry 6 --max-time 15 --retry-all-errors --retry-delay 20 --connect-timeout 60"

response=$(curl -fsSL $COCKPIT_RELEASE_URL)

if [[ $response =~ \"tag_name\":\ *\"([^\"]+)\" ]]; then
  cockpit_tag_name="${BASH_REMATCH[1]}"
  echo "Using cockpit tag: $cockpit_tag_name"
else
  echo "Could not find the latest release tag of Cockpit."
  exit 1
fi

# Images pulling

BLUEROBOTICS_COCKPIT_EXT="goaschris/cockpit:$cockpit_tag_name"

docker pull $BLUEROBOTICS_COCKPIT_EXT

# Settings creation

SETTINGS_BASE_DIR="/root/.config/blueos/kraken"

mkdir -p "${SETTINGS_BASE_DIR}"

# Check if the directory creation was successful
if [[ ! -d "${SETTINGS_BASE_DIR}" ]]; then
  echo "Failed to create directory ${SETTINGS_BASE_DIR}"
  exit 1
fi

# Creates kraken V2 settings with default extensions

cat > "${SETTINGS_BASE_DIR}/settings-2.json" <<EOF
{
  "VERSION": 2,
  "extensions": [
    {
      "docker": "goaschris/cockpit",
      "enabled": true,
      "identifier": "goaschris.cockpit",
      "name": "RemoraCockpit",
      "permissions": "{\"ExposedPorts\":{\"8000/tcp\":{}},\"HostConfig\":{\"PortBindings\":{\"8000/tcp\":[{\"HostPort\":\"\"}]}}}",
      "tag": "$cockpit_tag_name",
      "user_permissions": ""
    }
  ],
  "manifests": []
}
EOF

echo "Default extensions settings configured successfully."
