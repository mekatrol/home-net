#pragma once

#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"

#define EXTERNAL_LED_STRING_COUNT 4
#define LED_STRING_MAXIMUM_PHYSICAL_LENGTH 2048

typedef struct {
    size_t physical_length;
    size_t control_length;
    uint8_t red;
    uint8_t green;
    uint8_t blue;
    uint8_t intensity_percent;
} led_string_settings_t;

esp_err_t led_controller_start(void);

// Applies a preview to the LEDs and RAM only. Call led_controller_save_settings()
// separately when the user explicitly chooses to write the preview to flash.
esp_err_t led_controller_preview_string(size_t string_index, const led_string_settings_t *settings);
esp_err_t led_controller_save_settings(void);
void led_controller_get_settings(led_string_settings_t strings[EXTERNAL_LED_STRING_COUNT]);
