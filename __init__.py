from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, Event
from homeassistant.const import CONF_MAC, EVENT_HOMEASSISTANT_STOP
from homeassistant.components import bluetooth

from datetime import timedelta
import asyncio

from .const import DOMAIN
from .coordinator import PranaCoordinator
import logging

PLATFORMS = ["fan", "switch"]
CLIENT = "client"
CONFIG = "config"
SENSOR_TYPES = {
    "voc": ["VOC", "ppb", "mdi:gauge"],
    "co2": ["CO2", "ppm", "mdi:gauge"],
    
    # "temperature": ["Temperature", "°C", "mdi:thermometer"],
    # "humidity": ["Humidity", "%", "mdi:water-percent"],
    "speed": ["Speed", "level", "mdi:gauge"],
}

SCAN_INTERVAL = timedelta(seconds=30)
DEFAULT_MEDIAN = 1
CONF_MEDIAN = "median"
LOGGER = logging.getLogger(__name__)

from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.discovery import load_platform, async_load_platform
from homeassistant.helpers.dispatcher import dispatcher_send
from homeassistant.helpers.event import async_track_time_interval, call_later
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.const import (
    CONF_MAC,
    CONF_DEVICES,
    CONF_MONITORED_CONDITIONS,
    CONF_NAME,
    CONF_SENSORS,
    CONF_SCAN_INTERVAL,
    EVENT_HOMEASSISTANT_START,
)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry_LOGGER) -> bool:
    """Set up PRANA from a config entry."""
    address = entry.data[CONF_MAC]

    if not (ble_device := bluetooth.async_ble_device_from_address(hass, address)):
        raise ConfigEntryNotReady(
            f"Could not find Prana with address {address}. Try power cycling the device or move the bluetooth coordinator closer"
        )

    coordinator = PranaCoordinator(address, hass)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Fetch initial data
    await coordinator.async_config_entry_first_refresh()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    async def _async_stop(event: Event) -> None:
        """Close the connection."""
        await coordinator.stop()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_stop)
    )
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.stop()
    return unload_ok

async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    coordinator = hass.data[DOMAIN].pop(entry.entry_id)
    if entry.title != coordinator.name:
        await hass.config_entries.async_reload(entry.entry_id)
