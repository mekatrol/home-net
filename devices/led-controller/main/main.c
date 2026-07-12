#include <stddef.h>
#include <stdint.h>

#include "esp_check.h"
#include "esp_log.h"
#include "driver/rmt_encoder.h"
#include "driver/rmt_tx.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

// The ESP32-S3 board sold under the supplied Amazon listing routes its single
// onboard WS2812 addressable RGB LED data input to GPIO 21. GPIO 10 is used by
// the visually similar ESP32-C3 version, which caused the first firmware build
// to transmit successfully on a pin that was not connected to this board's LED.
#define ONBOARD_ADDRESSABLE_LED_GPIO 21
#define ONBOARD_ADDRESSABLE_LED_COUNT 1

// WS2812 devices expect an 800 kbit/s waveform. A 10 MHz Remote Control
// Transceiver (RMT) resolution gives the driver enough timing precision to
// generate that waveform without tying up either processor core.
#define ADDRESSABLE_LED_RMT_RESOLUTION_HZ 10000000
#define ADDRESSABLE_LED_RMT_MEMORY_SYMBOLS 64
#define ADDRESSABLE_LED_RMT_QUEUE_DEPTH 1
#define COLOR_DISPLAY_TIME_MILLISECONDS 1000

static const char *TAG = "led_controller";

typedef struct {
    const char *name;
    uint8_t red;
    uint8_t green;
    uint8_t blue;
} display_color_t;

static const display_color_t DISPLAY_COLORS[] = {
    {.name = "red", .red = 32, .green = 0, .blue = 0},
    {.name = "green", .red = 0, .green = 32, .blue = 0},
    {.name = "blue", .red = 0, .green = 0, .blue = 32},
    {.name = "yellow", .red = 32, .green = 32, .blue = 0},
    {.name = "cyan", .red = 0, .green = 32, .blue = 32},
    {.name = "magenta", .red = 32, .green = 0, .blue = 32},
    {.name = "white", .red = 24, .green = 24, .blue = 24},
};

typedef struct {
    rmt_channel_handle_t transmit_channel;
    rmt_encoder_handle_t byte_encoder;
} addressable_led_driver_t;

static esp_err_t create_onboard_addressable_led(addressable_led_driver_t *addressable_led)
{
    const rmt_tx_channel_config_t transmit_channel_configuration = {
        .gpio_num = ONBOARD_ADDRESSABLE_LED_GPIO,
        .clk_src = RMT_CLK_SRC_DEFAULT,
        .resolution_hz = ADDRESSABLE_LED_RMT_RESOLUTION_HZ,
        .mem_block_symbols = ADDRESSABLE_LED_RMT_MEMORY_SYMBOLS,
        .trans_queue_depth = ADDRESSABLE_LED_RMT_QUEUE_DEPTH,
        .intr_priority = 0,
        .flags.invert_out = false,
        .flags.with_dma = false,
        .flags.allow_pd = false,
        .flags.init_level = 0,
    };

    // At 10 MHz, one RMT duration tick is 100 ns. These timings encode a
    // logical zero as 0.3 us high / 0.9 us low and a logical one as
    // 0.9 us high / 0.3 us low, both within the WS2812 timing tolerances.
    const rmt_bytes_encoder_config_t byte_encoder_configuration = {
        .bit0 = {
            .level0 = 1,
            .duration0 = 3,
            .level1 = 0,
            .duration1 = 9,
        },
        .bit1 = {
            .level0 = 1,
            .duration0 = 9,
            .level1 = 0,
            .duration1 = 3,
        },
        .flags.msb_first = true,
    };

    ESP_RETURN_ON_ERROR(
        rmt_new_tx_channel(&transmit_channel_configuration, &addressable_led->transmit_channel),
        TAG,
        "Could not create the RMT transmit channel"
    );
    ESP_RETURN_ON_ERROR(
        rmt_new_bytes_encoder(&byte_encoder_configuration, &addressable_led->byte_encoder),
        TAG,
        "Could not create the WS2812 byte encoder"
    );
    return rmt_enable(addressable_led->transmit_channel);
}

static esp_err_t display_color(
    const addressable_led_driver_t *addressable_led,
    const display_color_t *display_color
)
{
    // WS2812 wire order is green, red, blue even though colors are normally
    // expressed as RGB. RMT sends the most-significant bit of each byte first.
    const uint8_t green_red_blue_data[] = {
        display_color->green,
        display_color->red,
        display_color->blue,
    };
    const rmt_transmit_config_t transmit_configuration = {
        .loop_count = 0,
        .flags.eot_level = 0,
        .flags.queue_nonblocking = 0,
    };

    ESP_RETURN_ON_ERROR(
        rmt_transmit(
            addressable_led->transmit_channel,
            addressable_led->byte_encoder,
            green_red_blue_data,
            sizeof(green_red_blue_data),
            &transmit_configuration
        ),
        TAG,
        "Could not transmit a color to the WS2812"
    );

    // Wait until RMT has copied and sent the stack-backed color bytes. The
    // following one-second delay also holds the line low far longer than the
    // WS2812 reset/latch minimum before the next color is sent.
    return rmt_tx_wait_all_done(addressable_led->transmit_channel, -1);
}

void app_main(void)
{
    addressable_led_driver_t onboard_addressable_led = {0};
    ESP_ERROR_CHECK(create_onboard_addressable_led(&onboard_addressable_led));

    ESP_LOGI(TAG, "Cycling the onboard WS2812 on GPIO %d", ONBOARD_ADDRESSABLE_LED_GPIO);

    size_t color_index = 0;
    while (true) {
        const display_color_t *current_display_color = &DISPLAY_COLORS[color_index];

        ESP_ERROR_CHECK(display_color(&onboard_addressable_led, current_display_color));
        ESP_LOGI(TAG, "Displaying %s", current_display_color->name);

        color_index = (color_index + 1) % (sizeof(DISPLAY_COLORS) / sizeof(DISPLAY_COLORS[0]));
        vTaskDelay(pdMS_TO_TICKS(COLOR_DISPLAY_TIME_MILLISECONDS));
    }
}
