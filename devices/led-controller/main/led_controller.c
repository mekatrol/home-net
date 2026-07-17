#include "led_controller.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "driver/rmt_encoder.h"
#include "driver/rmt_tx.h"
#include "driver/spi_master.h"
#include "esp_check.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "nvs.h"
#include "sdkconfig.h"

#define ADDRESSABLE_LED_RMT_RESOLUTION_HZ 10000000
#define ADDRESSABLE_LED_RMT_MEMORY_SYMBOLS 48
#define ONBOARD_ADDRESSABLE_LED_GPIO 21
#define ONBOARD_LED_SPI_CLOCK_HZ 2400000
#define LED_REFRESH_INTERVAL_MILLISECONDS 500
#define LED_REFRESH_TASK_PRIORITY 4
#define LED_REFRESH_TASK_STACK_SIZE 3072
#define SETTINGS_NAMESPACE "led-strings"
#define SETTINGS_VERSION 1

static const char *TAG = "led-controller";

typedef struct {
    const char *name;
    int gpio_number;
    led_string_settings_t settings;
    rmt_channel_handle_t transmit_channel;
    rmt_encoder_handle_t byte_encoder;
} external_led_string_t;

static external_led_string_t external_led_strings[EXTERNAL_LED_STRING_COUNT] = {
    {.name = "string-1", .gpio_number = CONFIG_LED_CONTROLLER_STRING_1_GPIO},
    {.name = "string-2", .gpio_number = CONFIG_LED_CONTROLLER_STRING_2_GPIO},
    {.name = "string-3", .gpio_number = CONFIG_LED_CONTROLLER_STRING_3_GPIO},
    {.name = "string-4", .gpio_number = CONFIG_LED_CONTROLLER_STRING_4_GPIO},
};

static SemaphoreHandle_t state_mutex;
static spi_device_handle_t onboard_led_spi_device;
static led_string_settings_t onboard_led_settings = {
    .physical_length = 1,
    .control_length = 1,
};

static bool settings_are_valid(const led_string_settings_t *settings)
{
    return settings->physical_length <= LED_STRING_MAXIMUM_PHYSICAL_LENGTH &&
           settings->control_length <= settings->physical_length &&
           settings->intensity_percent <= 100;
}

static esp_err_t initialize_external_string(external_led_string_t *string)
{
    const rmt_tx_channel_config_t channel_configuration = {
        .gpio_num = string->gpio_number,
        .clk_src = RMT_CLK_SRC_DEFAULT,
        .resolution_hz = ADDRESSABLE_LED_RMT_RESOLUTION_HZ,
        .mem_block_symbols = ADDRESSABLE_LED_RMT_MEMORY_SYMBOLS,
        .trans_queue_depth = 1,
        .flags.invert_out = false,
        .flags.with_dma = false,
        .flags.allow_pd = false,
        .flags.init_level = 0,
    };
    const rmt_bytes_encoder_config_t encoder_configuration = {
        .bit0 = {.level0 = 1, .duration0 = 3, .level1 = 0, .duration1 = 9},
        .bit1 = {.level0 = 1, .duration0 = 9, .level1 = 0, .duration1 = 3},
        .flags.msb_first = true,
    };

    ESP_RETURN_ON_ERROR(rmt_new_tx_channel(&channel_configuration, &string->transmit_channel), TAG, "Could not create RMT channel for %s", string->name);
    ESP_RETURN_ON_ERROR(rmt_new_bytes_encoder(&encoder_configuration, &string->byte_encoder), TAG, "Could not create RMT encoder for %s", string->name);
    return rmt_enable(string->transmit_channel);
}

static esp_err_t initialize_onboard_led(void)
{
    // The ESP32-S3 has four RMT (Remote Control Transceiver) transmit
    // channels, and the four external strings use all of them. SPI (Serial
    // Peripheral Interface) drives the single onboard WS2812 without taking a
    // channel away from an external string.
    const spi_bus_config_t bus_configuration = {
        .mosi_io_num = ONBOARD_ADDRESSABLE_LED_GPIO,
        .miso_io_num = -1,
        .sclk_io_num = -1,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
        .max_transfer_sz = 16,
    };
    const spi_device_interface_config_t device_configuration = {
        .clock_speed_hz = ONBOARD_LED_SPI_CLOCK_HZ,
        .mode = 0,
        .spics_io_num = -1,
        .queue_size = 1,
    };
    ESP_RETURN_ON_ERROR(spi_bus_initialize(SPI2_HOST, &bus_configuration, SPI_DMA_DISABLED), TAG, "Could not initialize onboard LED SPI bus");
    return spi_bus_add_device(SPI2_HOST, &device_configuration, &onboard_led_spi_device);
}

static esp_err_t transmit_onboard_settings(void)
{
    // This board's onboard addressable LED expects red-green-blue wire order,
    // unlike the green-red-blue order used by the external strings.
    const uint8_t red_green_blue[] = {
        (uint8_t)(((uint16_t)onboard_led_settings.red * onboard_led_settings.intensity_percent) / 100),
        (uint8_t)(((uint16_t)onboard_led_settings.green * onboard_led_settings.intensity_percent) / 100),
        (uint8_t)(((uint16_t)onboard_led_settings.blue * onboard_led_settings.intensity_percent) / 100),
    };
    uint8_t encoded_data[9] = {0};
    size_t encoded_bit_index = 0;

    // Each WS2812 data bit is expanded into three SPI bits. At 2.4 MHz, 100
    // represents a zero and 110 represents a one with the required waveform.
    for (size_t byte_index = 0; byte_index < sizeof(red_green_blue); byte_index++) {
        for (int source_bit = 7; source_bit >= 0; source_bit--) {
            const uint8_t encoded_bits = (red_green_blue[byte_index] & (1U << source_bit)) ? 0x6 : 0x4;
            for (int encoded_bit = 2; encoded_bit >= 0; encoded_bit--) {
                if ((encoded_bits & (1U << encoded_bit)) != 0) {
                    encoded_data[encoded_bit_index / 8] |= 1U << (7 - (encoded_bit_index % 8));
                }
                encoded_bit_index++;
            }
        }
    }

    spi_transaction_t transaction = {
        .length = sizeof(encoded_data) * 8,
        .tx_buffer = encoded_data,
    };
    ESP_RETURN_ON_ERROR(spi_device_transmit(onboard_led_spi_device, &transaction), TAG, "Could not update onboard LED");
    vTaskDelay(pdMS_TO_TICKS(1));
    return ESP_OK;
}

static esp_err_t transmit_settings(external_led_string_t *string, size_t transmit_length)
{
    if (transmit_length == 0) {
        return ESP_OK;
    }

    // External WS2812 strings use green-red-blue (GRB) wire order. The
    // intensity is applied to each colour component while constructing the
    // frame, leaving the selected colour itself unchanged in the settings.
    uint8_t *frame = calloc(transmit_length, 3);
    ESP_RETURN_ON_FALSE(frame != NULL, ESP_ERR_NO_MEM, TAG, "Could not allocate frame for %s", string->name);
    const uint8_t green = (uint8_t)(((uint16_t)string->settings.green * string->settings.intensity_percent) / 100);
    const uint8_t red = (uint8_t)(((uint16_t)string->settings.red * string->settings.intensity_percent) / 100);
    const uint8_t blue = (uint8_t)(((uint16_t)string->settings.blue * string->settings.intensity_percent) / 100);
    for (size_t led_index = 0; led_index < string->settings.control_length; led_index++) {
        frame[led_index * 3] = green;
        frame[led_index * 3 + 1] = red;
        frame[led_index * 3 + 2] = blue;
    }
    // calloc() deliberately leaves every LED after control_length black. A
    // complete physical-length frame is always sent so LEDs which were lit by
    // an earlier, longer control preview are actively switched off.
    const rmt_transmit_config_t transmit_configuration = {.loop_count = 0, .flags.eot_level = 0, .flags.queue_nonblocking = 0};
    esp_err_t result = rmt_transmit(string->transmit_channel, string->byte_encoder, frame, transmit_length * 3, &transmit_configuration);
    if (result == ESP_OK) {
        result = rmt_tx_wait_all_done(string->transmit_channel, portMAX_DELAY);
    }
    free(frame);
    return result;
}

static void load_saved_settings(void)
{
    nvs_handle_t storage;
    esp_err_t result = nvs_open(SETTINGS_NAMESPACE, NVS_READONLY, &storage);
    if (result == ESP_ERR_NVS_NOT_FOUND) {
        ESP_LOGI(TAG, "No saved LED string settings; starting with all strings off");
        return;
    }
    if (result != ESP_OK) {
        ESP_LOGE(TAG, "Could not open saved LED settings: %s", esp_err_to_name(result));
        return;
    }

    uint8_t saved_version = 0;
    if (nvs_get_u8(storage, "version", &saved_version) != ESP_OK || saved_version != SETTINGS_VERSION) {
        ESP_LOGW(TAG, "Ignoring saved LED settings with an unsupported version");
        nvs_close(storage);
        return;
    }

    for (size_t index = 0; index < EXTERNAL_LED_STRING_COUNT; index++) {
        char key[8];
        snprintf(key, sizeof(key), "string%u", (unsigned)(index + 1));
        led_string_settings_t saved_settings = {0};
        size_t saved_size = sizeof(saved_settings);
        result = nvs_get_blob(storage, key, &saved_settings, &saved_size);
        if (result == ESP_OK && saved_size == sizeof(saved_settings) && settings_are_valid(&saved_settings)) {
            external_led_strings[index].settings = saved_settings;
        } else if (result != ESP_ERR_NVS_NOT_FOUND) {
            ESP_LOGW(TAG, "Ignoring invalid saved settings for string %u", (unsigned)(index + 1));
        }
    }
    led_string_settings_t saved_onboard_settings = {0};
    size_t saved_onboard_size = sizeof(saved_onboard_settings);
    result = nvs_get_blob(storage, "onboard", &saved_onboard_settings, &saved_onboard_size);
    if (result == ESP_OK && saved_onboard_size == sizeof(saved_onboard_settings) &&
        settings_are_valid(&saved_onboard_settings) &&
        saved_onboard_settings.physical_length == 1 && saved_onboard_settings.control_length == 1) {
        onboard_led_settings = saved_onboard_settings;
    } else if (result != ESP_ERR_NVS_NOT_FOUND) {
        ESP_LOGW(TAG, "Ignoring invalid saved settings for onboard LED");
    }
    nvs_close(storage);
}

static void refresh_led_outputs(void *task_parameter)
{
    (void)task_parameter;
    TickType_t next_refresh_time = xTaskGetTickCount();

    while (true) {
        // WS2812 pixels retain their last received colour only while they stay
        // powered. Re-sending the complete frames lets a string recover within
        // about 500 ms when its power is switched off and back on, even though
        // none of the controller settings changed.
        vTaskDelayUntil(&next_refresh_time, pdMS_TO_TICKS(LED_REFRESH_INTERVAL_MILLISECONDS));

        xSemaphoreTake(state_mutex, portMAX_DELAY);
        for (size_t index = 0; index < EXTERNAL_LED_STRING_COUNT; index++) {
            const esp_err_t result = transmit_settings(
                &external_led_strings[index],
                external_led_strings[index].settings.physical_length
            );
            if (result != ESP_OK) {
                ESP_LOGE(TAG, "Could not refresh string %u: %s", (unsigned)(index + 1), esp_err_to_name(result));
            }
        }
        const esp_err_t onboard_result = transmit_onboard_settings();
        if (onboard_result != ESP_OK) {
            ESP_LOGE(TAG, "Could not refresh onboard LED: %s", esp_err_to_name(onboard_result));
        }
        xSemaphoreGive(state_mutex);
    }
}

esp_err_t led_controller_start(void)
{
    state_mutex = xSemaphoreCreateMutex();
    ESP_RETURN_ON_FALSE(state_mutex != NULL, ESP_ERR_NO_MEM, TAG, "Could not create LED state mutex");
    load_saved_settings();
    ESP_RETURN_ON_ERROR(initialize_onboard_led(), TAG, "Could not initialize onboard LED");
    ESP_RETURN_ON_ERROR(transmit_onboard_settings(), TAG, "Could not apply saved settings to onboard LED");
    for (size_t index = 0; index < EXTERNAL_LED_STRING_COUNT; index++) {
        ESP_RETURN_ON_ERROR(initialize_external_string(&external_led_strings[index]), TAG, "Could not initialize external string %u", (unsigned)(index + 1));
        ESP_RETURN_ON_ERROR(transmit_settings(&external_led_strings[index], external_led_strings[index].settings.physical_length), TAG, "Could not apply saved settings to string %u", (unsigned)(index + 1));
    }
    ESP_RETURN_ON_FALSE(
        xTaskCreate(refresh_led_outputs, "refresh-led-outputs", LED_REFRESH_TASK_STACK_SIZE, NULL, LED_REFRESH_TASK_PRIORITY, NULL) == pdPASS,
        ESP_ERR_NO_MEM,
        TAG,
        "Could not create LED refresh task"
    );
    return ESP_OK;
}

esp_err_t led_controller_preview_string(size_t string_index, const led_string_settings_t *settings)
{
    ESP_RETURN_ON_FALSE(string_index < EXTERNAL_LED_STRING_COUNT && settings != NULL && settings_are_valid(settings), ESP_ERR_INVALID_ARG, TAG, "Invalid LED string settings");
    xSemaphoreTake(state_mutex, portMAX_DELAY);
    external_led_string_t *string = &external_led_strings[string_index];
    const size_t previous_physical_length = string->settings.physical_length;
    string->settings = *settings;
    // If the physical-length preview is reduced, transmit through the previous
    // end once. This clears LEDs that would otherwise retain their last colour.
    const size_t transmit_length = previous_physical_length > settings->physical_length
        ? previous_physical_length : settings->physical_length;
    const esp_err_t result = transmit_settings(string, transmit_length);
    xSemaphoreGive(state_mutex);
    return result;
}

esp_err_t led_controller_preview_onboard(const led_string_settings_t *settings)
{
    ESP_RETURN_ON_FALSE(
        settings != NULL && settings_are_valid(settings) &&
        settings->physical_length == 1 && settings->control_length == 1,
        ESP_ERR_INVALID_ARG,
        TAG,
        "Invalid onboard LED settings"
    );
    xSemaphoreTake(state_mutex, portMAX_DELAY);
    onboard_led_settings = *settings;
    const esp_err_t result = transmit_onboard_settings();
    xSemaphoreGive(state_mutex);
    return result;
}

esp_err_t led_controller_save_settings(void)
{
    nvs_handle_t storage;
    ESP_RETURN_ON_ERROR(nvs_open(SETTINGS_NAMESPACE, NVS_READWRITE, &storage), TAG, "Could not open LED settings storage");
    xSemaphoreTake(state_mutex, portMAX_DELAY);
    esp_err_t result = nvs_set_u8(storage, "version", SETTINGS_VERSION);
    for (size_t index = 0; result == ESP_OK && index < EXTERNAL_LED_STRING_COUNT; index++) {
        char key[8];
        snprintf(key, sizeof(key), "string%u", (unsigned)(index + 1));
        result = nvs_set_blob(storage, key, &external_led_strings[index].settings, sizeof(external_led_strings[index].settings));
    }
    if (result == ESP_OK) {
        result = nvs_set_blob(storage, "onboard", &onboard_led_settings, sizeof(onboard_led_settings));
    }
    if (result == ESP_OK) {
        result = nvs_commit(storage);
    }
    xSemaphoreGive(state_mutex);
    nvs_close(storage);
    return result;
}

void led_controller_get_settings(led_string_settings_t strings[EXTERNAL_LED_STRING_COUNT])
{
    xSemaphoreTake(state_mutex, portMAX_DELAY);
    for (size_t index = 0; index < EXTERNAL_LED_STRING_COUNT; index++) {
        strings[index] = external_led_strings[index].settings;
    }
    xSemaphoreGive(state_mutex);
}

void led_controller_get_onboard_settings(led_string_settings_t *settings)
{
    if (settings == NULL) {
        return;
    }
    xSemaphoreTake(state_mutex, portMAX_DELAY);
    *settings = onboard_led_settings;
    xSemaphoreGive(state_mutex);
}
