import network

try:
    import uasyncio as asyncio
except ImportError:
    import asyncio


class WlanHelper:

    def __init__(self):
        self._is_connected = False
        self._wlan = None
        self._ip = ""
        self._netmask = ""
        self._gateway = ""
        self._name_server = ""

    def is_connected(self):
        return self._wlan is not None and self._wlan.isconnected()

    def ip(self):
        return self._ip

    def netmask(self):
        return self._netmask

    def gateway(self):
        return self._gateway

    def name_server(self):
        return self._name_server

    async def connect(self, ssid, password):
        # Make sure is disconnected
        self.disconnect()
        await asyncio.sleep(1)

        # Init network configuration
        self._wlan = network.WLAN(network.STA_IF)

        # Make active and connect
        self._wlan.active(True)
        self._wlan.connect(ssid, password)

        # Wait for connect or fail
        wait = 30
        while wait > 0:
            if self._wlan.status() < 0 or self._wlan.status() >= 3:
                break
            wait -= 1
            await asyncio.sleep(1)
        self._init_info()

    def disconnect(self):
        if self._wlan is not None:
            self._wlan.disconnect()
            self._wlan.active(False)
            self._wlan = None

    def _init_info(self):
        if self._wlan is None:
            self._ip = ""
            self._netmask = ""
            self._gateway = ""
            self._name_server = ""

        info = self._wlan.ifconfig()

        self._ip = info[0]
        self._netmask = info[1]
        self._gateway = info[2]
        self._name_server = info[3]
