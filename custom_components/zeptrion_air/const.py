from __future__ import annotations

"""Constants for zeptrion_air."""

from logging import Logger, getLogger

from homeassistant.const import Platform

LOGGER: Logger = getLogger(__package__)

DOMAIN: str = "zeptrion_air"

CONF_NAME: str ="name"
CONF_IP_ADDRESS: str = "ip_address"
CONF_PORT: str = "port"
CONF_HOSTNAME: str = "hostname"
CONF_TYPE: str = "type"
CONF_FIRMWARE: str = "firmware"
CONF_STEP_DURATION_MS: str = "step_duration_ms"

# Services
SERVICE_BLIND_RECALL_S1: str = "blind_recall_s1"
SERVICE_BLIND_RECALL_S2: str = "blind_recall_s2"
SERVICE_BLIND_RECALL_S3: str = "blind_recall_s3"
SERVICE_BLIND_RECALL_S4: str = "blind_recall_s4"

# Default values
DEFAULT_STEP_DURATION_MS: int = 250

# Validation values
MIN_STEP_DURATION_MS: int = 100
MAX_STEP_DURATION_MS: int = 32000

# Platforms
PLATFORMS: list[Platform] = [Platform.COVER, Platform.BUTTON, Platform.SENSOR]

# Events
ZEPTRION_AIR_WEBSOCKET_MESSAGE: str = "zeptrion_air_websocket_message"
