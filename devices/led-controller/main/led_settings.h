#pragma once

#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"
#include "led_controller.h"

#define MINIMUM_LEDS_PER_STRING 1
#define MAXIMUM_LEDS_PER_STRING 2048

/**
 * Loads the configured LED counts from non-volatile storage.
 *
 * A string without a saved value uses its menuconfig default. This allows a
 * newly flashed controller to work without requiring a settings write first.
 */
esp_err_t led_settings_load_counts(
    size_t led_counts[EXTERNAL_LED_STRING_COUNT]
);

/** Loads the saved onboard colour, defaulting to off when none is stored. */
esp_err_t led_settings_load_onboard_color(
    uint8_t *red,
    uint8_t *green,
    uint8_t *blue
);

/** Saves every user setting with one non-volatile storage commit. */
esp_err_t led_settings_save(
    const size_t led_counts[EXTERNAL_LED_STRING_COUNT],
    uint8_t red,
    uint8_t green,
    uint8_t blue
);
