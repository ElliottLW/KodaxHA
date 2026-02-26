"""Constants for the KodaxHA integration."""

DOMAIN = "kodaxha"

# Config entry keys
CONF_CAMERA_IP = "camera_ip"
CONF_SCAN_INTERVAL = "scan_interval"

# Config entry keys — stream/snapshot live in options so they can be changed
# post-install without re-adding the integration
CONF_STREAM_URL = "stream_url"
CONF_SNAPSHOT_URL = "snapshot_url"

# Defaults
DEFAULT_NAME = "Kodak Camera"
DEFAULT_SCAN_INTERVAL = 30  # seconds
DEFAULT_PORT = 80

# URL registered for the Lovelace card
CARD_URL = "/kodaxha/kodaxha-card.js"

# Camera API commands
CMD_GET_CAMINFO = "get_caminfo"
CMD_GET_TEMP_HUMID = "get_temp_humid"
CMD_GET_VERSION = "get_version"
CMD_GET_WIFI_STRENGTH = "get_wifi_strength"
CMD_GET_MAC_ADDRESS = "get_mac_address"
CMD_GET_SESSION_KEY = "get_session_key"
CMD_RESTART = "restart_system"
CMD_MELODY_STOP = "melodystop"

# ── Night vision options ────────────────────────────────────────────────────
NIGHT_VISION_AUTO = "auto"
NIGHT_VISION_ON = "on"
NIGHT_VISION_OFF = "off"

NIGHT_VISION_OPTIONS: dict[str, int] = {
    NIGHT_VISION_AUTO: 0,
    NIGHT_VISION_ON: 1,
    NIGHT_VISION_OFF: 2,
}
NIGHT_VISION_VALUES: dict[int, str] = {v: k for k, v in NIGHT_VISION_OPTIONS.items()}

# ── Resolution options ──────────────────────────────────────────────────────
RESOLUTION_480P = "480p (Standard)"
RESOLUTION_720P = "720p (HD)"

RESOLUTION_OPTIONS: dict[str, int] = {
    RESOLUTION_480P: 480,
    RESOLUTION_720P: 720,
}
RESOLUTION_VALUES: dict[int, str] = {v: k for k, v in RESOLUTION_OPTIONS.items()}

# ── Camera orientation options ──────────────────────────────────────────────
FLIP_NORMAL = "normal"
FLIP_CEILING = "ceiling_mount"

FLIP_OPTIONS: dict[str, int] = {
    FLIP_NORMAL: 0,
    FLIP_CEILING: 1,
}
FLIP_VALUES: dict[int, str] = {v: k for k, v in FLIP_OPTIONS.items()}

# ── Motion/sound sensitivity options ───────────────────────────────────────
SENSITIVITY_LOW = "low"
SENSITIVITY_MEDIUM = "medium"
SENSITIVITY_HIGH = "high"

SENSITIVITY_OPTIONS: dict[str, int] = {
    SENSITIVITY_LOW: 1,
    SENSITIVITY_MEDIUM: 3,
    SENSITIVITY_HIGH: 5,
}
SENSITIVITY_VALUES: dict[int, str] = {v: k for k, v in SENSITIVITY_OPTIONS.items()}
