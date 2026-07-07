#include "status_led.h"

#include <stdbool.h>
#include <stddef.h>

#include "driver/rmt_encoder.h"
#include "driver/rmt_tx.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sdkconfig.h"

#define STARTUP_FLASH_INTERVAL_MS 200
#define RMT_LED_RESOLUTION_HZ 10000000
#define RMT_TX_QUEUE_DEPTH 4
#define RMT_MEMORY_BLOCK_SYMBOLS 64

static const char *TAG = "mqtt-switch-led";

static rmt_channel_handle_t led_channel;
static rmt_encoder_handle_t led_encoder;

static const rmt_symbol_word_t ws2812_zero = {
    .level0 = 1,
    .duration0 = 0.3 * RMT_LED_RESOLUTION_HZ / 1000000,
    .level1 = 0,
    .duration1 = 0.9 * RMT_LED_RESOLUTION_HZ / 1000000,
};

static const rmt_symbol_word_t ws2812_one = {
    .level0 = 1,
    .duration0 = 0.9 * RMT_LED_RESOLUTION_HZ / 1000000,
    .level1 = 0,
    .duration1 = 0.3 * RMT_LED_RESOLUTION_HZ / 1000000,
};

static const rmt_symbol_word_t ws2812_reset = {
    .level0 = 0,
    .duration0 = RMT_LED_RESOLUTION_HZ / 1000000 * 50 / 2,
    .level1 = 0,
    .duration1 = RMT_LED_RESOLUTION_HZ / 1000000 * 50 / 2,
};

static size_t encode_ws2812_byte_stream(
    const void *data,
    size_t data_size,
    size_t symbols_written,
    size_t symbols_free,
    rmt_symbol_word_t *symbols,
    bool *done,
    void *arg
)
{
    if (symbols_free < 8) {
        return 0;
    }

    size_t data_pos = symbols_written / 8;
    const uint8_t *bytes = data;
    if (data_pos < data_size) {
        size_t symbol_pos = 0;
        for (int bitmask = 0x80; bitmask != 0; bitmask >>= 1) {
            symbols[symbol_pos++] = (bytes[data_pos] & bitmask) ? ws2812_one : ws2812_zero;
        }
        return symbol_pos;
    }

    symbols[0] = ws2812_reset;
    *done = true;
    return 1;
}

void mqtt_switch_status_led_set(uint8_t red, uint8_t green, uint8_t blue)
{
    uint8_t bytes[] = {green, red, blue};
    rmt_transmit_config_t transmit_config = {
        .loop_count = 0,
    };

    /*
     * The Wemos ESP32-S2 Mini onboard RGB LED is a WS2812-style addressable
     * LED. It expects a green/red/blue byte stream followed by a low reset
     * pulse, not normal GPIO on/off writes.
     */
    ESP_ERROR_CHECK(rmt_transmit(led_channel, led_encoder, bytes, sizeof(bytes), &transmit_config));
    ESP_ERROR_CHECK(rmt_tx_wait_all_done(led_channel, 100));
}

void mqtt_switch_status_led_configure(void)
{
    rmt_tx_channel_config_t channel_config = {
        .clk_src = RMT_CLK_SRC_DEFAULT,
        .gpio_num = CONFIG_MQTT_SWITCH_STATUS_LED_GPIO,
        .mem_block_symbols = RMT_MEMORY_BLOCK_SYMBOLS,
        .resolution_hz = RMT_LED_RESOLUTION_HZ,
        .trans_queue_depth = RMT_TX_QUEUE_DEPTH,
        .flags.init_level = 0,
    };

    rmt_simple_encoder_config_t encoder_config = {
        .callback = encode_ws2812_byte_stream,
    };

    ESP_LOGI(TAG, "Configuring RGB status LED on GPIO%d", CONFIG_MQTT_SWITCH_STATUS_LED_GPIO);
    ESP_ERROR_CHECK(rmt_new_tx_channel(&channel_config, &led_channel));
    ESP_ERROR_CHECK(rmt_new_simple_encoder(&encoder_config, &led_encoder));
    ESP_ERROR_CHECK(rmt_enable(led_channel));
    mqtt_switch_status_led_set(0, 0, 0);
}

void mqtt_switch_status_led_flash_startup(void)
{
    for (int i = 0; i < 2; i++) {
        mqtt_switch_status_led_set(0, 1, 0);
        vTaskDelay(pdMS_TO_TICKS(STARTUP_FLASH_INTERVAL_MS));
        mqtt_switch_status_led_set(0, 0, 0);
        vTaskDelay(pdMS_TO_TICKS(STARTUP_FLASH_INTERVAL_MS));
    }
}
