from homeassistant.components.switch import (
    DOMAIN as ENTITY_DOMAIN,
    SwitchEntity,
    DEVICE_CLASS_SWITCH,
    DEVICE_CLASS_OUTLET,
)

"""Support for Prana fan."""
from . import DOMAIN

from datetime import datetime, timedelta
import logging
import math
from homeassistant.components.fan import (
    SUPPORT_SET_SPEED,
    SUPPORT_DIRECTION,
    SUPPORT_PRESET_MODE,
    FanEntity,
)

from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from homeassistant.helpers import device_registry
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.const import STATE_OFF
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import dispatcher_send, async_dispatcher_connect
from homeassistant.util.percentage import (
    int_states_in_range,
    percentage_to_ranged_value,
    ranged_value_to_percentage,
)

LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, config_entry, async_add_devices):
    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    async_add_devices([PranaHeating(hass, coordinator, config_entry.data["name"], config_entry.entry_id)])
    async_add_devices([PranaWinterMode(hass, coordinator, config_entry.data["name"], config_entry.entry_id)])
    async_add_devices([PranaAutoMode(hass, coordinator, config_entry.data["name"], config_entry.entry_id)])

class BasePranaSwitch(CoordinatorEntity, SwitchEntity):
    # Implement one of these methods.
    """Representation of a Prana fan."""
    def __init__(self, hass, coordinator, name: str, entry_id: str):
        """Initialize the sensor."""
        super().__init__(coordinator)
        _attr_has_entity_name = True
        self._hass = hass
        self.coordinator = coordinator
        self._name = name
        self._entry_id = entry_id
        self._hass.bus.async_listen("prana_update", self._handle_coordinator_update)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
    
    @property
    def available(self):
        """Return state of the fan."""
        return self.coordinator.lastRead != None and (self.coordinator.lastRead > datetime.now() - timedelta(minutes=5))

    @property
    def device_info(self):
        """Return device info."""
        return DeviceInfo(
            identifiers={
                # Serial numbers are unique identifiers within a specific domain
                (DOMAIN, self.coordinator.mac)
            },
            name=self.name,
            connections={(device_registry.CONNECTION_NETWORK_MAC, self.coordinator.mac)},
        )

class PranaHeating(BasePranaSwitch):
    @property
    def name(self) -> str:
        """Return the name of the switch."""
        return self._name + " heating"

    @property
    def is_on(self):
        """Return state of the fan."""
        return self.coordinator.mini_heating_enabled

    async def async_turn_on(self, **kwargs) -> None:
        """Turn on the entity."""
        await self.coordinator.set_heating(True)

    async def async_turn_off(self, **kwargs) -> None:
        """Turn off the entity."""
        await self.coordinator.set_heating(False)
    
    @property
    def unique_id(self) -> str:
        """Return a unique, Home Assistant friendly identifier for this entity."""
        return self.coordinator.mac.replace(":", "")+ "_heating"

class PranaWinterMode(BasePranaSwitch):
    @property
    def unique_id(self) -> str:
        """Return a unique, Home Assistant friendly identifier for this entity."""
        return self.coordinator.mac.replace(":", "")+ "_winter_mode"

    @property
    def name(self) -> str:
        """Return the name of the switch."""
        return self._name + " winter mode"

    @property
    def is_on(self):
        """Return state of the fan."""
        return self.coordinator.winter_mode_enabled

    async def async_turn_on(self, **kwargs) -> None:
        """Turn on the entity."""
        await self.coordinator.set_winter_mode(True)

    async def async_turn_off(self, **kwargs) -> None:
        """Turn off the entity."""
        await self.coordinator.set_winter_mode(False)

class PranaAutoMode(BasePranaSwitch):
    @property
    def unique_id(self) -> str:
        """Return a unique, Home Assistant friendly identifier for this entity."""
        return self.coordinator.mac.replace(":", "")+ "_auto_mode"

    @property
    def name(self) -> str:
        """Return the name of the switch."""
        return self._name + " auto mode"

    @property
    def is_on(self):
        """Return state of the fan."""
        return self.coordinator.winter_mode_enabled

    async def async_turn_on(self, **kwargs) -> None:
        """Turn on the entity."""
        await self.coordinator.toggle_auto_mode()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn off the entity."""
        await self.coordinator.toggle_auto_mode()