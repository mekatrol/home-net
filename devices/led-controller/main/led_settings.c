#include "led_settings.h"

#include <stdint.h>

#include "esp_check.h"
#include "esp_log.h"
#include "nvs.h"
#include "sdkconfig.h"

#define SETTINGS_NAMESPACE "led-settings"
#define ONBOARD_COLOR_KEY "onboard-color"

static const char *TAG = "led-settings";

static const size_t default_led_counts[EXTERNAL_LED_STRING_COUNT] = {
    CONFIG_LED_CONTROLLER_STRING_1_LENGTH,
    CONFIG_LED_CONTROLLER_STRING_2_LENGTH,
    CONFIG_LED_CONTROLLER_STRING_3_LENGTH,
    CONFIG_LED_CONTROLLER_STRING_4_LENGTH,
};

// Non-volatile storage (NVS) keys are intentionally stable and short. NVS
// limits key names to 15 characters, and retaining these names lets later
// firmware versions add pattern settings without invalidating saved counts.
static const char *const led_count_keys[EXTERNAL_LED_STRING_COUNT] = {
    "string1-count",
    "string2-count",
    "string3-count",
    "string4-count",
};

static bool led_count_is_valid(size_t led_count)
{
    return led_count >= MINIMUM_LEDS_PER_STRING &&
        led_count <= MAXIMUM_LEDS_PER_STRING;
}

esp_err_t led_settings_load_counts(size_t led_counts[EXTERNAL_LED_STRING_COUNT])
{
    ESP_RETURN_ON_FALSE(led_counts != NULL, ESP_ERR_INVALID_ARG, TAG, "LED count output is required");

    nvs_handle_t storage_handle;
    const esp_err_t open_result = nvs_open(SETTINGS_NAMESPACE, NVS_READONLY, &storage_handle);
    if (open_result == ESP_ERR_NVS_NOT_FOUND) {
        // A fresh device has no namespace until the first setting is saved.
        // Treat that as an empty settings set rather than a boot failure.
        for (size_t string_index = 0; string_index < EXTERNAL_LED_STRING_COUNT; string_index++) {
            led_counts[string_index] = default_led_counts[string_index];
        }
        return ESP_OK;
    }
    ESP_RETURN_ON_ERROR(open_result, TAG, "Could not open LED settings");

    for (size_t string_index = 0; string_index < EXTERNAL_LED_STRING_COUNT; string_index++) {
        uint16_t stored_led_count;
        const esp_err_t read_result = nvs_get_u16(
            storage_handle,
            led_count_keys[string_index],
            &stored_led_count
        );

        if (read_result == ESP_ERR_NVS_NOT_FOUND) {
            led_counts[string_index] = default_led_counts[string_index];
        } else if (read_result != ESP_OK) {
            nvs_close(storage_handle);
            ESP_RETURN_ON_ERROR(read_result, TAG, "Could not read string %u LED count", (unsigned)(string_index + 1));
        } else if (!led_count_is_valid(stored_led_count)) {
            // Corrupt or old values must not drive an unbounded allocation.
            // Falling back keeps the device bootable so the setting can be
            // corrected through the web interface.
            ESP_LOGW(
                TAG,
                "Ignoring invalid saved count %u for string %u",
                (unsigned)stored_led_count,
                (unsigned)(string_index + 1)
            );
            led_counts[string_index] = default_led_counts[string_index];
        } else {
            led_counts[string_index] = stored_led_count;
        }
    }

    nvs_close(storage_handle);
    return ESP_OK;
}

esp_err_t led_settings_load_onboard_color(uint8_t *red, uint8_t *green, uint8_t *blue)
{
    ESP_RETURN_ON_FALSE(red != NULL && green != NULL && blue != NULL, ESP_ERR_INVALID_ARG, TAG, "Onboard colour output is required");

    // Black is both the safe power-up state and the factory default. Set it
    // before reading so a fresh NVS namespace or a missing key needs no special
    // cleanup path.
    *red = 0;
    *green = 0;
    *blue = 0;

    nvs_handle_t storage_handle;
    const esp_err_t open_result = nvs_open(SETTINGS_NAMESPACE, NVS_READONLY, &storage_handle);
    if (open_result == ESP_ERR_NVS_NOT_FOUND) {
        return ESP_OK;
    }
    ESP_RETURN_ON_ERROR(open_result, TAG, "Could not open LED settings");

    uint8_t stored_red_green_blue[3];
    size_t stored_size = sizeof(stored_red_green_blue);
    const esp_err_t read_result = nvs_get_blob(
        storage_handle,
        ONBOARD_COLOR_KEY,
        stored_red_green_blue,
        &stored_size
    );
    nvs_close(storage_handle);

    if (read_result == ESP_ERR_NVS_NOT_FOUND) {
        return ESP_OK;
    }
    if (read_result == ESP_ERR_NVS_INVALID_LENGTH || stored_size != sizeof(stored_red_green_blue)) {
        ESP_LOGW(TAG, "Ignoring saved onboard colour with invalid size %u", (unsigned)stored_size);
        return ESP_OK;
    }
    ESP_RETURN_ON_ERROR(read_result, TAG, "Could not read onboard LED colour");

    *red = stored_red_green_blue[0];
    *green = stored_red_green_blue[1];
    *blue = stored_red_green_blue[2];
    return ESP_OK;
}

esp_err_t led_settings_save(
    const size_t led_counts[EXTERNAL_LED_STRING_COUNT],
    uint8_t red,
    uint8_t green,
    uint8_t blue
)
{
    ESP_RETURN_ON_FALSE(led_counts != NULL, ESP_ERR_INVALID_ARG, TAG, "LED counts are required");
    for (size_t string_index = 0; string_index < EXTERNAL_LED_STRING_COUNT; string_index++) {
        ESP_RETURN_ON_FALSE(led_count_is_valid(led_counts[string_index]), ESP_ERR_INVALID_ARG, TAG, "Invalid LED count for string %u", (unsigned)(string_index + 1));
    }

    nvs_handle_t storage_handle;
    ESP_RETURN_ON_ERROR(
        nvs_open(SETTINGS_NAMESPACE, NVS_READWRITE, &storage_handle),
        TAG,
        "Could not open LED settings"
    );

    esp_err_t save_result = ESP_OK;
    for (size_t string_index = 0; string_index < EXTERNAL_LED_STRING_COUNT && save_result == ESP_OK; string_index++) {
        save_result = nvs_set_u16(
            storage_handle,
            led_count_keys[string_index],
            (uint16_t)led_counts[string_index]
        );
    }

    // Storing all colour channels in one blob prevents a reset between three
    // separate writes from leaving a partially updated colour. The single
    // commit below makes the counts and colour durable as one settings action.
    const uint8_t red_green_blue[] = {red, green, blue};
    if (save_result == ESP_OK) {
        save_result = nvs_set_blob(
            storage_handle,
            ONBOARD_COLOR_KEY,
            red_green_blue,
            sizeof(red_green_blue)
        );
    }
    if (save_result == ESP_OK) {
        save_result = nvs_commit(storage_handle);
    }
    nvs_close(storage_handle);
    ESP_RETURN_ON_ERROR(save_result, TAG, "Could not save LED settings");
    return ESP_OK;
}
