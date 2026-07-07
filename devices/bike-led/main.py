from machine import Pin
import neopixel
import time

# Number of LEDs in each strip
NUM_LEDS_PER_STRING = 30

# GPIOs for the 4 WS2812B strings
PINS = [10, 11, 12, 13]

# Create NeoPixel objects
strips = [neopixel.NeoPixel(Pin(pin, Pin.OUT), NUM_LEDS_PER_STRING) for pin in PINS]

# Colors
RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)
WHITE = (255, 255, 255)
OFF = (0, 0, 0)

FLASH_INTERVAL = 0.2
CHASER_DELAY = 0.05
CHASER_WIDTH = 4  # number of LEDs on at once


def fill_strip(strip, color):
    for i in range(NUM_LEDS_PER_STRING):
        strip[i] = color
    strip.write()


def fill_all(color):
    for strip in strips:
        fill_strip(strip, color)


def clear_all():
    fill_all(OFF)


def flash_red_three_times():
    for _ in range(3):
        fill_all(RED)
        time.sleep(FLASH_INTERVAL)
        clear_all()
        time.sleep(FLASH_INTERVAL)


def chaser(color):
    clear_all()

    for i in range(NUM_LEDS_PER_STRING + CHASER_WIDTH):
        for strip in strips:
            # turn all off first
            for j in range(NUM_LEDS_PER_STRING):
                strip[j] = OFF

            # turn on a 3-LED window
            for k in range(CHASER_WIDTH):
                idx = i - k
                if 0 <= idx < NUM_LEDS_PER_STRING:
                    strip[idx] = color

            strip.write()

        time.sleep(CHASER_DELAY)


while True:
    flash_red_three_times()
    chaser(GREEN)
    chaser(BLUE)
    chaser(WHITE)