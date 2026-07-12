#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"

#define EXTERNAL_LED_STRING_COUNT 4

typedef struct {
    bool enabled;
    size_t led_count;
    const char *pattern_name;
} external_led_string_state_t;

typedef struct {
    uint8_t red;
    uint8_t green;
    uint8_t blue;
} onboard_led_color_t;

typedef struct {
    size_t led_count;
    size_t bytes_per_led;
    size_t sequence_count;
    const uint8_t *sequence_bytes;
} external_led_sequence_configuration_t;

typedef struct {
    size_t sequence_count;
    const uint8_t *red_green_blue_sequence_bytes;
} onboard_led_sequence_configuration_t;

esp_err_t led_controller_start(void);
esp_err_t led_controller_set_external_enabled(size_t string_index, bool enabled);
esp_err_t led_controller_set_onboard_color(uint8_t red, uint8_t green, uint8_t blue);
esp_err_t led_controller_apply_onboard_sequences(
    const onboard_led_sequence_configuration_t *configuration,
    uint32_t sequence_interval_milliseconds
);
esp_err_t led_controller_apply_external_sequences(
    size_t string_index,
    const external_led_sequence_configuration_t *configuration,
    uint32_t sequence_interval_milliseconds
);
void led_controller_get_state(
    external_led_string_state_t external_strings[EXTERNAL_LED_STRING_COUNT],
    onboard_led_color_t *onboard_color
);
