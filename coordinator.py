import asyncio
from datetime import datetime, timedelta
import binascii 
import async_timeout

from homeassistant.components import bluetooth
from homeassistant.helpers.dispatcher import dispatcher_send
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import PranaState, Speed, PranaSensorsState

from typing import Dict, List, Union, Optional
from bleak.backends.device import BLEDevice
from bleak.backends.service import BleakGATTCharacteristic, BleakGATTServiceCollection
from bleak.exc import BleakDBusError
from bleak_retry_connector import BLEAK_RETRY_EXCEPTIONS as BLEAK_EXCEPTIONS
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    BleakError,
    BleakNotFoundError,
    ble_device_has_changed,
    establish_connection,
)
from typing import Any, TypeVar, cast, Tuple
from collections.abc import Callable
from math import log2
import traceback
import asyncio
import logging
import struct


LOGGER = logging.getLogger(__name__)
WRITE_CHARACTERISTIC_UUIDS = ["0000cccc-0000-1000-8000-00805f9b34fb"]
READ_CHARACTERISTIC_UUIDS  = ["0000cccc-0000-1000-8000-00805f9b34fb"]

DEFAULT_ATTEMPTS = 3
DISCONNECT_DELAY = 120
BLEAK_BACKOFF_TIME = 0.25
RETRY_BACKOFF_EXCEPTIONS = (BleakDBusError,)
WrapFuncType = TypeVar("WrapFuncType", bound=Callable[..., Any])

def retry_bluetooth_connection_error(func: WrapFuncType) -> WrapFuncType:
    """Define a wrapper to retry on bleak error.

    The accessory is allowed to disconnect us any time so
    we need to retry the operation.
    """

    async def _async_wrap_retry_bluetooth_connection_error(
        self: "Prana", *args: Any, **kwargs: Any
    ) -> Any:
        attempts = DEFAULT_ATTEMPTS
        max_attempts = attempts - 1

        for attempt in range(attempts):
            try:
                return await func(self, *args, **kwargs)
            except BleakNotFoundError:
                # The lock cannot be found so there is no
                # point in retrying.
                raise
            except RETRY_BACKOFF_EXCEPTIONS as err:
                if attempt >= max_attempts:
                    LOGGER.debug("%s: %s error calling %s, reach max attempts (%s/%s)",self.name,type(err),func,attempt,max_attempts,exc_info=True,)
                    raise
                LOGGER.debug("%s: %s error calling %s, backing off %ss, retrying (%s/%s)...",self.name,type(err),func,BLEAK_BACKOFF_TIME,attempt,max_attempts,exc_info=True,)
                await asyncio.sleep(BLEAK_BACKOFF_TIME)
            except BLEAK_EXCEPTIONS as err:
                if attempt >= max_attempts:
                    LOGGER.debug("%s: %s error calling %s, reach max attempts (%s/%s): %s",self.name,type(err),func,attempt,max_attempts,err,exc_info=True,)
                    raise
                LOGGER.debug("%s: %s error calling %s, retrying  (%s/%s)...: %s",self.name,type(err),func,attempt,max_attempts,err,exc_info=True,)

    return cast(WrapFuncType, _async_wrap_retry_bluetooth_connection_error)

class PranaCoordinator(DataUpdateCoordinator):
    CONTROL_SERVICE_UUID = "0000baba-0000-1000-8000-00805f9b34fb"
    CONTROL_RW_CHARACTERISTIC_UUID = "0000cccc-0000-1000-8000-00805f9b34fb"
    STATE_MSG_PREFIX = b"\xbe\xef"
    MAX_BRIGHTNESS = 6

    class Cmd:
        ENABLE_HIGH_SPEED = bytearray([0xBE, 0xEF, 0x04, 0x07])
        ENABLE_NIGHT_MODE = bytearray([0xBE, 0xEF, 0x04, 0x06])
        TOGGLE_FLOW_LOCK = bytearray([0xBE, 0xEF, 0x04, 0x09])
        TOGGLE_HEATING = bytearray([0xBE, 0xEF, 0x04, 0x05])
        TOGGLE_WINTER_MODE = bytearray([0xBE, 0xEF, 0x04, 0x16])

        SPEED_UP = bytearray([0xBE, 0xEF, 0x04, 0x0C])
        SPEED_DOWN = bytearray([0xBE, 0xEF, 0x04, 0x0B])
        SPEED_IN_UP = bytearray([0xBE, 0xEF, 0x04, 0x0E])
        SPEED_IN_DOWN = bytearray([0xBE, 0xEF, 0x04, 0x0F])
        SPEED_OUT_UP = bytearray([0xBE, 0xEF, 0x04, 0x11])
        SPEED_OUT_DOWN = bytearray([0xBE, 0xEF, 0x04, 0x12])

        FLOW_IN_OFF = bytearray([0xBE, 0xEF, 0x04, 0x0D])
        FLOW_OUT_OFF = bytearray([0xBE, 0xEF, 0x04, 0x10])

        START = bytearray([0xBE, 0xEF, 0x04, 0x0A])
        STOP = bytearray([0xBE, 0xEF, 0x04, 0x01])
        READ_STATE = bytearray([0xBE, 0xEF, 0x05, 0x01, 0x00, 0x00, 0x00, 0x00, 0x5A])
        READ_DEVICE_DETAILS = bytearray([0xBE, 0xEF, 0x05, 0x02, 0x00, 0x00, 0x00, 0x00, 0x5A])
        CHANGE_BRIGHTNESS = bytearray([0xBE, 0xEF, 0x04, 0x02])
        AUTO_MODE = bytearray([0xBE, 0xEF, 0x04, 0x18])

    def __init__(self, address, hass) -> None:
        """Initialize prana coordinator."""
        super().__init__(
            hass,
            LOGGER,
            name="Prana ventilation",
            update_interval=timedelta(seconds=30),
        )

        self.loop = asyncio.get_running_loop()
        self.mac = address
        self._hass = hass
        self._device: BLEDevice | None = None
        self._device = bluetooth.async_ble_device_from_address(self._hass, address, connectable=True)
        self._connect_lock: asyncio.Lock = asyncio.Lock()
        self._client: BleakClientWithServiceCache | None = None
        self._disconnect_timer: asyncio.TimerHandle | None = None
        self._cached_services: BleakGATTServiceCollection | None = None
        self._expected_disconnect = False
        self._write_uuid = None
        self._read_uuid = None

        # Device data
        self.speed = 0 #calculated
        self.speed_locked: Optional[int] = None
        self.speed_in: Optional[int] = None
        self.speed_out: Optional[int] = None
        self.night_mode: Optional[bool] = None
        self.auto_mode: Optional[bool] = None
        self.flows_locked: Optional[bool] = None
        self.is_on: Optional[bool] = None
        self.mini_heating_enabled: Optional[bool] = None
        self.winter_mode_enabled: Optional[bool] = None
        self.is_input_fan_on: Optional[bool] = None
        self.is_output_fan_on: Optional[bool] = None
        self.brightness: Optional[int] = None
        self.sensors: Optional[PranaSensorsState] = None
        self.timestamp: Optional[datetime.datetime] = None
        self.lastRead = None
        self.co2 = None
        self.voc = None

    async def _async_update_data(self):
        """Fetch data from device."""
        try:
            # Note: asyncio.TimeoutError and aiohttp.ClientError are already
            # handled by the data update coordinator.
            await self.get_status_details()

        except (Exception) as error:
            self.is_on = False
            LOGGER.error("Error getting status: %s", error)
            track = traceback.format_exc()
            LOGGER.debug(track)

    async def _write(self, data: bytearray, await_response: bool = False):
        """Send command to device and read response."""
        await self._ensure_connected()
        return await self._write_while_connected(data, await_response)

    async def _write_while_connected(self, data: bytearray, await_response: bool = False):
        LOGGER.error("Before command")
        await self._client.write_gatt_char(self._write_uuid, data, await_response)

        # Update the info after each command
        if(self.Cmd.READ_STATE != data):
            LOGGER.error("Before read state")
            return await self._client.write_gatt_char(self._write_uuid, self.Cmd.READ_STATE, True)

    @property
    def rssi(self):
        return self._device.rssi

# NEW DATA
    # @retry_bluetooth_connection_error
    # async def set_high_speed(self):
    #     await self._write(self.Cmd.ENABLE_HIGH_SPEED)

    @retry_bluetooth_connection_error
    async def speed_up(self):
        await self._write(self.Cmd.SPEED_UP)

    @retry_bluetooth_connection_error
    async def speed_down(self):
        await self._write(self.Cmd.SPEED_DOWN)

    @retry_bluetooth_connection_error
    async def set_low_speed(self):
        await self._write(self.Cmd.ENABLE_NIGHT_MODE)

    @retry_bluetooth_connection_error
    async def set_night_mode(self):
        await self._write(self.Cmd.ENABLE_NIGHT_MODE)

    @retry_bluetooth_connection_error
    async def set_normal_speed(self):
        await self.set_speed(Speed.SPEED_3)

    @retry_bluetooth_connection_error
    async def get_status_details(self):
        return await self._write(self.Cmd.READ_STATE)

    @retry_bluetooth_connection_error
    async def set_speed(self, speed: int):
        if (speed == self.speed):
            return

        if not self.is_on:
            await self.turn_on()

        direction_up = speed > self.speed
        counter = self.speed
        if direction_up:
            while counter < speed:
                await self.speed_up()
                counter += 1
        else:
            while counter > speed:
                await self.speed_down()
                counter -= 1
        self.speed = speed

    @retry_bluetooth_connection_error
    async def set_brightness(self, brightness: int):
        if brightness < 0 or brightness > 6:
            raise ValueError("brightness value must be in range 0-6")
        original_state = await self.get_status_details()
        original_brightness = none_throws(original_state.brightness)
        if brightness == original_brightness:
            return
        if brightness > original_brightness:
            counter = brightness - original_brightness
        else:
            counter = brightness + (self.MAX_BRIGHTNESS - original_brightness)
        while counter > 0:
            await self.brightness_up()
            counter -= 1

    @retry_bluetooth_connection_error
    async def set_brightness_pct(self, brightness_pct: int):
        """
        Set brightness in percents (0-100)
        :param brightness_pct: integer in 0-100 range
        :return:
        """
        if brightness_pct < 0 or brightness_pct > 100:
            raise ValueError("brightness_pct is percent value (range 0-100)")
        return await self.set_brightness(round(self.MAX_BRIGHTNESS * brightness_pct / 100))

    @retry_bluetooth_connection_error
    async def brightness_up(self):
        await self._write(self.Cmd.CHANGE_BRIGHTNESS)

    @retry_bluetooth_connection_error
    async def set_heating(self, enable: bool):
        if self.mini_heating_enabled != enable:
            LOGGER.debug("Set heating mode")
            await self._write(self.Cmd.TOGGLE_HEATING, True)
            self.mini_heating_enabled = enable

    @retry_bluetooth_connection_error
    async def set_winter_mode(self, enable: bool):
        if self.winter_mode_enabled != enable:
            return await self._write(self.Cmd.TOGGLE_WINTER_MODE)

    @retry_bluetooth_connection_error
    async def turn_off(self):
        LOGGER.debug("turn off")
        self.is_on = False
        return await self._write(self.Cmd.STOP)

    @retry_bluetooth_connection_error
    async def turn_on(self):
        LOGGER.debug("turn on")
        self.is_on = True
        return await self._write(self.Cmd.START)

    @retry_bluetooth_connection_error
    async def toggle_air_in_off(self):
        self.is_input_fan_on = not self.is_input_fan_on
        return await self._write(self.Cmd.FLOW_IN_OFF)

    @retry_bluetooth_connection_error
    async def toggle_air_out_off(self):
        self.is_output_fan_on = not self.self.is_output_fan_on
        return await self._write(self.Cmd.FLOW_OUT_OFF)

    @retry_bluetooth_connection_error
    async def toggle_auto_mode(self):
        self.auto_mode = not self.auto_mode
        return await self._write(self.Cmd.AUTO_MODE)
    
    @retry_bluetooth_connection_error
    async def set_auto_mode(self):
        if not self.auto_mode:
            self.auto_mode = True
            await self._write(self.Cmd.AUTO_MODE)


    def __parse_state(self, data: bytearray) -> Optional[PranaState]:
        if not data[:2] == self.STATE_MSG_PREFIX:
            return None
        s = PranaState()
        s.timestamp = datetime.now()
        s.brightness = int(log2(data[12]) + 1)
        s.speed_locked = int(data[26] / 10)
        s.speed_in = int(data[30] / 10)
        s.speed_out = int(data[34] / 10)
        s.auto_mode = bool(data[20])
        s.night_mode = bool(data[16])
        s.flows_locked = bool(data[22])
        s.is_on = bool(data[10])
        s.mini_heating_enabled = bool(data[14])
        s.winter_mode_enabled = bool(data[42])
        s.is_input_fan_on = bool(data[28])
        s.is_output_fan_on = bool(data[32])

        if not self.is_on:
            self.speed = 0
        elif self.auto_mode:
            self.speed = self.speed_in #same as self.speedOut
        elif self.speed_locked:
            self.speed = self.speed_locked
        elif self.air_in and self.air_in:
            self.speed = int((self.speed_in + self.speed_out) / 2)
        elif self.isAirInOn:
            self.speed = self.speed_in
        elif self.isAirOutOn:
            self.speed = self.speed_out

        # Reading sensors
        sensors = PranaSensorsState()
        sensors.humidity = int(data[60] - 128)
        sensors.pressure = 512 + int(data[78])
        # co2 and voc
        sensors.co2 = int(struct.unpack_from(">h", data, 61)[0] & 0b0011111111111111)
        sensors.voc = int(struct.unpack_from(">h", data, 63)[0] & 0b0011111111111111)
        if 0 < sensors.co2 < 10000:
            # Different version of firmware ???
            sensors.temperature_in = float(struct.unpack_from(">h", data, 51)[0] & 0b0011111111111111) / 10.0
            sensors.temperature_out = float(struct.unpack_from(">h", data, 54)[0] & 0b0011111111111111) / 10.0
        else:
            sensors.temperature_in = float(data[49]) / 10
            sensors.temperature_out = float(data[55]) / 10
        # Add sensors to the state only in case device has corresponding hardware
        if sensors.humidity > 0:
            s.sensors = sensors
        return s

    async def _notification_handler(self, _sender: int, data: bytearray) -> None:
        """Handle notification responses."""
        state = self.__parse_state(data)
        self.lastRead = datetime.now()
        LOGGER.debug("State data from notifiation: %s", state)
        if state is not None:
            dict_state = state.to_dict()
            for key in dict_state:
                setattr(self, key, dict_state[key])
            LOGGER.debug("Send update event %s", dict_state)
            await self.async_request_refresh()
            

# NEW DATA END








# OLD
    @retry_bluetooth_connection_error
    async def _ensure_connected(self) -> None:
        """Ensure connection to device is established."""
        if self._connect_lock.locked():
            LOGGER.debug(
                "%s: Connection already in progress, waiting for it to complete; RSSI: %s",
                self.name,
                self.rssi,
            )
        if self._client and self._client.is_connected:
            self._reset_disconnect_timer()
            return
        async with self._connect_lock:
            # Check again while holding the lock
            if self._client and self._client.is_connected:
                self._reset_disconnect_timer()
                return
            LOGGER.debug("%s: Connecting; RSSI: %s", self.name, self.rssi)
            client = await establish_connection(
                BleakClientWithServiceCache,
                self._device,
                self.name,
                self._disconnected,
                cached_services=self._cached_services,
                ble_device_callback=lambda: self._device,
            )
            LOGGER.debug("%s: Connected; RSSI: %s", self.name, self.rssi)

            self._read_uuid = READ_CHARACTERISTIC_UUIDS[0]
            self._write_uuid = WRITE_CHARACTERISTIC_UUIDS[0]
            self._cached_services = client.services
            self._client = client
            self._reset_disconnect_timer()

            LOGGER.debug("%s: Subscribe to notifications; RSSI: %s", self.name, self.rssi)
            await client.start_notify(self._read_uuid, self._notification_handler)
    

    def _reset_disconnect_timer(self) -> None:
        """Reset disconnect timer."""
        if self._disconnect_timer:
            self._disconnect_timer.cancel()
        self._expected_disconnect = False
        self._disconnect_timer = self.loop.call_later(
            DISCONNECT_DELAY, self._disconnect
        )

    def _disconnected(self, client: BleakClientWithServiceCache) -> None:
        """Disconnected callback."""
        if self._expected_disconnect:
            LOGGER.debug("%s: Disconnected from device; RSSI: %s", self.name, self.rssi)
            return
        LOGGER.warning("%s: Device unexpectedly disconnected; RSSI: %s",self.name,self.rssi,)

    def _disconnect(self) -> None:
        """Disconnect from device."""
        self._disconnect_timer = None
        asyncio.create_task(self._execute_timed_disconnect())

    async def stop(self) -> None:
        """Stop the LEDBLE."""
        # LOGGER.debug("%s: Stop", self.name)
        await self._execute_disconnect()
        
    async def _execute_timed_disconnect(self) -> None:
        """Execute timed disconnection."""
        LOGGER.debug(
            "%s: Disconnecting after timeout of %s",
            self.name,
            DISCONNECT_DELAY,
        )
        await self._execute_disconnect()

    async def _execute_disconnect(self) -> None:
        """Execute disconnection."""
        async with self._connect_lock:
            read_char = self._read_uuid
            client = self._client
            self._expected_disconnect = True
            self._client = None
            self._write_uuid = None
            self._read_uuid = None
            if client and client.is_connected:
                await client.stop_notify(read_char)
                await client.disconnect()