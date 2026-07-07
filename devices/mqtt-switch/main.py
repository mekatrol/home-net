from machine import Pin, reset
from neopixel import NeoPixel

try:
    import utime as time
except ImportError:
    import time

try:
    import uasyncio as asyncio
except ImportError:
    import asyncio

try:
    import ujson as json
except ImportError:
    import json

from config import config
from wifi.wlan import WlanHelper

try:
    from mqtt import MQTTClient
except ImportError:
    from mqtt.mqtt_client import MQTTClient


DEFAULT_OUTPUT_PIN = 5
DEFAULT_STATUS_LED_PIN = 16
OUTPUT_INTERVAL_SECONDS = 0.1
STARTUP_FLASH_INTERVAL_SECONDS = 0.2
MQTT_INACTIVE_FLASH_HZ = 2
MQTT_RX_INDICATOR_SECONDS = 1
DEFAULT_MQTT_INACTIVITY_TIMEOUT_SECONDS = 3600
DEFAULT_MQTT_INACTIVITY_WARNING_SECONDS = 20
MINIMUM_MQTT_INACTIVITY_WARNING_SECONDS = 1
MINIMUM_MQTT_INACTIVITY_TIMEOUT_SECONDS = 1
MQTT_INACTIVITY_CHECK_SECONDS = 1


op_on = False
enabled_on = False
wlan = None
mqtt_client = None
tasks = {}
last_mqtt_rx_ms = 0
last_mqtt_indicator_ms = 0


def build_output_pin():
    output_pin = config.get("output_pin", DEFAULT_OUTPUT_PIN)
    return Pin(output_pin, Pin.OUT)


def build_status_led():
    led_pin = config.get("status_led_pin", DEFAULT_STATUS_LED_PIN)
    return Pin(led_pin, Pin.OUT)


output_pin = build_output_pin()
status_led = build_status_led()
pixel = NeoPixel(status_led, 1)


def get_int_config(name, default, minimum=1):
    value = config.get(name, default)

    try:
        value = int(value)
    except (TypeError, ValueError):
        return default

    if value < minimum:
        return default

    return value


def get_mqtt_inactivity_timeout_ms():
    timeout_seconds = get_int_config(
        "mqtt_inactivity_timeout",
        DEFAULT_MQTT_INACTIVITY_TIMEOUT_SECONDS,
        minimum=MINIMUM_MQTT_INACTIVITY_TIMEOUT_SECONDS,
    )
    return timeout_seconds * 1000


def get_mqtt_inactivity_warning_ms():
    warning_seconds = get_int_config(
        "mqtt_inactivity_warning_seconds",
        DEFAULT_MQTT_INACTIVITY_WARNING_SECONDS,
        minimum=MINIMUM_MQTT_INACTIVITY_WARNING_SECONDS,
    )
    return warning_seconds * 1000


MQTT_INACTIVITY_TIMEOUT_MS = get_mqtt_inactivity_timeout_ms()
MQTT_INACTIVITY_WARNING_MS = get_mqtt_inactivity_warning_ms()


def ticks_ms():
    try:
        return time.ticks_ms()
    except AttributeError:
        return int(time.time() * 1000)


def ticks_diff(now, then):
    try:
        return time.ticks_diff(now, then)
    except AttributeError:
        return now - then


def publish_status():
    if mqtt_client is None:
        return

    mqtt_client.publish(
        config["mqtt_status_topic"],
        '{{"enabled": {}, "on": {}}}'.format(
            "true" if enabled_on else "false", "true" if op_on else "false"
        ),
    )


def is_mqtt_inactivity_warning_active(now_ms=None):
    if mqtt_client is None or not last_mqtt_rx_ms:
        return False

    if now_ms is None:
        now_ms = ticks_ms()

    idle_ms = ticks_diff(now_ms, last_mqtt_rx_ms)
    return idle_ms >= MQTT_INACTIVITY_WARNING_MS


def is_mqtt_rx_indicator_active(now_ms=None):
    if not last_mqtt_indicator_ms:
        return False

    if now_ms is None:
        now_ms = ticks_ms()

    indicator_ms = MQTT_RX_INDICATOR_SECONDS * 1000
    return ticks_diff(now_ms, last_mqtt_indicator_ms) < indicator_ms


def on_mqtt_message(topic, msg):
    global enabled_on
    global op_on
    global last_mqtt_indicator_ms
    global last_mqtt_rx_ms

    last_mqtt_rx_ms = ticks_ms()
    last_mqtt_indicator_ms = last_mqtt_rx_ms

    if isinstance(topic, bytes):
        topic = topic.decode()

    if isinstance(msg, bytes):
        msg = msg.decode()

    try:
        payload = json.loads(msg)
        enabled_on = bool(payload.get("enabled", enabled_on))
        op_on = bool(payload.get("on", op_on))
    except (ValueError, TypeError, AttributeError):
        print("Invalid MQTT JSON:", msg)
        return

    publish_status()


async def output_control():
    while True:
        try:
            now_ms = ticks_ms()

            if is_mqtt_rx_indicator_active(now_ms):
                pixel[0] = (0, 1, 0)
                pixel.write()                
            elif is_mqtt_inactivity_warning_active(now_ms):
                # A blink cycle has two phases: ON then OFF.
                # For 2 Hz, each full cycle lasts 500 ms, so each phase lasts 250 ms.
                # Integer-dividing the current time by the phase length gives a phase number
                # that increments every 250 ms; even phases turn the LED on, odd phases turn it off.
                flash_phase_ms = 1000 // (MQTT_INACTIVE_FLASH_HZ * 2)
                flash_on = (now_ms // flash_phase_ms) % 2 == 0
                if flash_on:
                    pixel[0] = (0, 1, 0)
                else:
                    pixel[0] = (0, 0, 0)
                pixel.write()                
                
            else:
                pixel[0] = (0, 0, 0)
                pixel.write()                

            output_pin.value(enabled_on and op_on)
            await asyncio.sleep(OUTPUT_INTERVAL_SECONDS)
        except Exception as err:
            print("output_control error:", err)
            await asyncio.sleep(1)


async def flash_output(times=2, r=0, g=1, b=0):
    for _ in range(times):
        pixel[0] = (r, g, b)
        pixel.write()                
        await asyncio.sleep(STARTUP_FLASH_INTERVAL_SECONDS)
        pixel[0] = (0, 0, 0)
        pixel.write()                
        await asyncio.sleep(STARTUP_FLASH_INTERVAL_SECONDS)


def reset_mqtt():
    global mqtt_client
    global last_mqtt_indicator_ms
    global last_mqtt_rx_ms

    if mqtt_client is None:
        return

    try:
        mqtt_client.disconnect()
    except Exception:
        pass

    mqtt_client = None
    last_mqtt_indicator_ms = 0
    last_mqtt_rx_ms = 0


def reset_wifi():
    global wlan

    reset_mqtt()

    if wlan is None:
        return

    try:
        wlan.disconnect()
    except Exception:
        pass

    wlan = None


async def ensure_wifi():
    global wlan

    while wlan is None or not wlan.is_connected():
        helper = WlanHelper()

        try:
            await helper.connect(config["wlan_ssid"], config["wlan_pwd"])
        except Exception as err:
            print("Wi-Fi connect error:", err)

        if helper.is_connected():
            wlan = helper
            print("Wi-Fi connected")
            print("IP:", wlan.ip())
            return wlan

        print("Wi-Fi unavailable, retrying")
        await asyncio.sleep(5)


def build_mqtt_client():
    client = MQTTClient(
        client_id=config["mqtt_clientid"],
        server=config["mqtt_host"],
        user=config["mqtt_username"],
        password=config["mqtt_password"],
        keepalive=60,
    )
    client.set_callback(on_mqtt_message)
    return client


async def ensure_mqtt():
    global mqtt_client
    global last_mqtt_rx_ms

    while mqtt_client is None:
        await ensure_wifi()
        client = build_mqtt_client()

        try:
            print("MQTT connecting")
            client.connect()
            print("MQTT subscribing")
            client.subscribe(config["mqtt_set_topic"])
        except Exception as err:
            print("MQTT connect error:", err)

            try:
                client.disconnect()
            except Exception:
                pass

            if wlan is None or not wlan.is_connected():
                reset_wifi()

            await asyncio.sleep(5)
            continue

        mqtt_client = client
        last_mqtt_rx_ms = ticks_ms()
        print("MQTT connected")
        publish_status()
        return mqtt_client


async def mqtt_keepalive():
    while True:
        try:
            if mqtt_client is None:
                await asyncio.sleep(1)
                continue

            publish_status()
            mqtt_client.ping()
        except Exception as err:
            print("MQTT keepalive error:", err)
            reset_mqtt()

        await asyncio.sleep(30)


async def mqtt_listen():
    global last_mqtt_rx_ms

    while True:
        try:
            if mqtt_client is None:
                await asyncio.sleep(1)
                continue

            packet_type = mqtt_client.check_msg()
            if packet_type is not None:
                last_mqtt_rx_ms = ticks_ms()
        except Exception as err:
            print("MQTT listen error:", repr(err))

            if wlan is None or not wlan.is_connected():
                reset_wifi()
            else:
                reset_mqtt()

        await asyncio.sleep(0.1)


async def mqtt_inactivity_watchdog():
    while True:
        try:
            if mqtt_client is not None and last_mqtt_rx_ms:
                idle_ms = ticks_diff(ticks_ms(), last_mqtt_rx_ms)
                if idle_ms > MQTT_INACTIVITY_TIMEOUT_MS:
                    print("MQTT inactivity timeout, resetting device")
                    await asyncio.sleep(1)
                    reset()
        except Exception as err:
            print("MQTT inactivity watchdog error:", err)

        await asyncio.sleep(MQTT_INACTIVITY_CHECK_SECONDS)


async def connection_monitor():
    while True:
        try:
            if wlan is None or not wlan.is_connected():
                reset_wifi()
                await ensure_wifi()

            if mqtt_client is None:
                await ensure_mqtt()
        except Exception as err:
            print("Connection monitor error:", err)
            reset_wifi()
            await asyncio.sleep(1)

        await asyncio.sleep(1)


async def run_supervised(name, coroutine_fn):
    while True:
        try:
            await coroutine_fn()
        except Exception as err:
            print("Task crashed:", name, err)
            if name in ("mqtt_keepalive", "mqtt_listen", "connection_monitor"):
                reset_wifi()
            await asyncio.sleep(1)


def start_task(name, coroutine_fn):
    task = asyncio.create_task(run_supervised(name, coroutine_fn))
    tasks[name] = task
    return task


async def task_supervisor():
    while True:
        for name, coroutine_fn in (
            ("output_control", output_control),
            ("mqtt_keepalive", mqtt_keepalive),
            ("mqtt_listen", mqtt_listen),
            ("mqtt_inactivity_watchdog", mqtt_inactivity_watchdog),
            ("connection_monitor", connection_monitor),
        ):
            task = tasks.get(name)
            if task is None or task.done():
                print("Starting task:", name)
                start_task(name, coroutine_fn)

        await asyncio.sleep(2)


async def main():
    await ensure_wifi()
    await ensure_mqtt()
    await flash_output(2)

    start_task("output_control", output_control)
    start_task("mqtt_keepalive", mqtt_keepalive)
    start_task("mqtt_listen", mqtt_listen)
    start_task("mqtt_inactivity_watchdog", mqtt_inactivity_watchdog)
    start_task("connection_monitor", connection_monitor)
    asyncio.create_task(task_supervisor())

    while True:
        await asyncio.sleep(1)


asyncio.run(main())
