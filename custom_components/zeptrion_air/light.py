"""Light platform for Zeptrion Air."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import (
    ZeptrionAirApiClientCommunicationError,
    ZeptrionAirApiClientError,
)
from .const import DOMAIN, ZEPTRION_AIR_WEBSOCKET_MESSAGE

_LOGGER = logging.getLogger(__name__)

DIMMER_FULL_TRAVEL_MS = 3400


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Set up Zeptrion Air light entities from a config entry."""
    platform_data: dict[str, Any] | None = hass.data[DOMAIN].get(entry.entry_id)
    if not platform_data:
        _LOGGER.error("No platform_data found for entry ID %s", entry.entry_id)
        return False

    main_hub_device_info: dict[str, Any] = platform_data.get("hub_device_info", {})
    identified_channels_list: list[dict[str, Any]] = platform_data.get(
        "identified_channels", []
    )
    hub_serial: str | None = platform_data.get("hub_serial")

    if not hub_serial:
        _LOGGER.error("Hub serial not found in platform_data.")
        return False

    new_entities: list[ZeptrionAirLight] = []

    for channel_info_dict in identified_channels_list:
        channel_id: int | None = channel_info_dict.get("id")
        device_type: str | None = channel_info_dict.get("device_type")

        if channel_id is None or device_type not in ("light_switch", "light_dimmer"):
            continue

        desired_name: str = channel_info_dict.get("entity_base_name") or f"Channel {channel_id}"
        is_dimmer = device_type == "light_dimmer"

        hub_manufacturer: str = main_hub_device_info.get("manufacturer", "Feller AG")
        hub_sw_version: str | None = main_hub_device_info.get("sw_version")

        light_device_info: dict[str, Any] = {
            "identifiers": {(DOMAIN, f"{hub_serial}_ch{channel_id}")},
            "name": desired_name,
            "via_device": (DOMAIN, hub_serial),
            "manufacturer": hub_manufacturer,
            "sw_version": hub_sw_version,
            "model": f"Zeptrion Air Channel {channel_id} - {'Dimmer' if is_dimmer else 'Switch'}",
        }

        new_entities.append(
            ZeptrionAirLight(
                config_entry=entry,
                device_info_for_light_entity=light_device_info,
                channel_id=channel_id,
                hub_serial=hub_serial,
                is_dimmer=is_dimmer,
            )
        )

    if new_entities:
        _LOGGER.info("Adding %s ZeptrionAirLight entities.", len(new_entities))
        async_add_entities(new_entities)
    else:
        _LOGGER.info("No Zeptrion Air light entities to add.")

    return True


class ZeptrionAirLight(LightEntity):
    """Representation of a Zeptrion Air light."""

    def __init__(
        self,
        config_entry: ConfigEntry,
        device_info_for_light_entity: dict[str, Any],
        channel_id: int,
        hub_serial: str,
        is_dimmer: bool,
    ) -> None:
        """Initialize the light."""
        self.config_entry = config_entry
        self._channel_id = channel_id
        self._is_dimmer = is_dimmer

        self._attr_device_info = device_info_for_light_entity
        self._attr_name = str(device_info_for_light_entity.get("name") or f"Channel {channel_id}")
        self._attr_unique_id = f"zapp_{hub_serial}_ch{channel_id}_light"

        self._attr_is_on = False
        self._attr_brightness = 255 if is_dimmer else None
        self._last_nonzero_brightness = 255
        self._pending_refresh_task: asyncio.Task | None = None

        if is_dimmer:
            self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
            self._attr_color_mode = ColorMode.BRIGHTNESS
        else:
            self._attr_supported_color_modes = {ColorMode.ONOFF}
            self._attr_color_mode = ColorMode.ONOFF

    def _set_state_from_api_percent(self, value_0_100: int) -> None:
        """Apply a Zeptrion value (0-100) to the HA entity state.

        Important:
        - For dimmers, the Zeptrion API does not provide reliable current brightness.
          Therefore we only use this value to determine ON/OFF and keep HA brightness optimistic.
        - For switches, ON/OFF is enough anyway.
        """
        value_0_100 = max(0, min(100, int(value_0_100)))

        if self._is_dimmer:
            self._attr_is_on = value_0_100 > 0
            return

        self._attr_is_on = value_0_100 > 0

    async def _async_refresh_from_scan(self, delay: float = 0.0) -> None:
        """Refresh current state from /zrap/chscan/chX after an optional delay."""
        if delay > 0:
            await asyncio.sleep(delay)

        try:
            scan_data = await self.config_entry.runtime_data.client.async_get_channel_scan_info(
                self._channel_id
            )

            channel_key = f"ch{self._channel_id}"
            channel_data = (
                scan_data.get("chscan", {}).get(channel_key, {})
                if isinstance(scan_data, dict)
                else {}
            )

            raw_value = channel_data.get("val")
            if raw_value is None:
                _LOGGER.debug(
                    "No scan value returned for light %s (Channel %s): %s",
                    self._attr_name,
                    self._channel_id,
                    scan_data,
                )
                return

            self._set_state_from_api_percent(int(raw_value))
            self.async_write_ha_state()

        except Exception as e:
            _LOGGER.debug(
                "Could not refresh light state from scan for %s (Channel %s): %s",
                self._attr_name,
                self._channel_id,
                e,
            )

    def _schedule_refresh(self, delay: float) -> None:
        """Schedule a delayed refresh from scan endpoint."""
        if self.hass is None:
            return

        if self._pending_refresh_task and not self._pending_refresh_task.done():
            self._pending_refresh_task.cancel()

        self._pending_refresh_task = self.hass.async_create_task(
            self._async_refresh_from_scan(delay)
        )

    async def async_added_to_hass(self) -> None:
        """Handle entity added to HA."""
        await super().async_added_to_hass()

        self.async_on_remove(
            self.hass.bus.async_listen(
                ZEPTRION_AIR_WEBSOCKET_MESSAGE,
                self.async_handle_websocket_message,
            )
        )

        await self._async_refresh_from_scan()

    async def async_handle_websocket_message(self, event: Event) -> None:
        """Handle websocket events for this light."""
        message_data = event.data

        if message_data.get("channel") != self._channel_id:
            return

        if message_data.get("hub_unique_id") != self.config_entry.unique_id:
            return

        if message_data.get("source") != "eid1":
            return

        raw_value = message_data.get("value")
        if raw_value is None:
            return

        try:
            # Intentionally only update ON/OFF from websocket.
            # Do not overwrite brightness for dimmers.
            self._set_state_from_api_percent(int(raw_value))
            self.async_write_ha_state()
        except (ValueError, TypeError):
            _LOGGER.debug(
                "Ignoring non-integer websocket value for light %s (Channel %s): %s",
                self._attr_name,
                self._channel_id,
                raw_value,
            )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        client = self.config_entry.runtime_data.client

        try:
            if self._is_dimmer:
                brightness = kwargs.get(
                    ATTR_BRIGHTNESS,
                    self._last_nonzero_brightness or 255,
                )
                brightness = max(1, min(255, int(brightness)))

                # Optimistic HA state
                self._attr_is_on = True
                self._attr_brightness = brightness
                self._last_nonzero_brightness = brightness
                self.async_write_ha_state()

                await client.async_channel_set_brightness(self._channel_id, brightness)

                # Refresh only ON/OFF state afterwards (not brightness)
                refresh_delay = 0.35 + (
                    (255 - brightness) / 255 * (DIMMER_FULL_TRAVEL_MS / 1000)
                )
                self._schedule_refresh(refresh_delay)
            else:
                self._attr_is_on = True
                self.async_write_ha_state()

                await client.async_channel_on(self._channel_id)
                self._schedule_refresh(0.3)

        except (ZeptrionAirApiClientCommunicationError, ZeptrionAirApiClientError) as e:
            _LOGGER.error(
                "API error while turning on light %s (Channel %s): %s",
                self._attr_name,
                self._channel_id,
                e,
            )
            raise HomeAssistantError(
                f"Failed to turn on light {self.name} (Channel {self._channel_id}): {e}"
            ) from e

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        client = self.config_entry.runtime_data.client

        try:
            if self._is_dimmer and self._attr_brightness:
                self._last_nonzero_brightness = self._attr_brightness

            self._attr_is_on = False
            self.async_write_ha_state()

            await client.async_channel_off(self._channel_id)
            self._schedule_refresh(0.3)

        except (ZeptrionAirApiClientCommunicationError, ZeptrionAirApiClientError) as e:
            _LOGGER.error(
                "API error while turning off light %s (Channel %s): %s",
                self._attr_name,
                self._channel_id,
                e,
            )
            raise HomeAssistantError(
                f"Failed to turn off light {self.name} (Channel {self._channel_id}): {e}"
            ) from e
