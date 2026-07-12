#include "led_controller.h"

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
#include "sdkconfig.h"
#include "led_settings.h"

#define ONBOARD_ADDRESSABLE_LED_GPIO 21
#define ADDRESSABLE_LED_RMT_RESOLUTION_HZ 10000000
#define ADDRESSABLE_LED_RMT_MEMORY_SYMBOLS 48
#define LED_PATTERN_FRAME_MILLISECONDS 40
#define LED_PATTERN_TASK_STACK_SIZE 6144
#define LED_PATTERN_TASK_PRIORITY 5
#define LED_PATTERN_TASK_CORE 1
#define ONBOARD_SPI_CLOCK_HZ 2400000

static const char *TAG = "led-controller";

typedef enum {
    LED_PATTERN_SOLID,
    LED_PATTERN_CHASE,
    LED_PATTERN_RAINBOW,
    LED_PATTERN_BLINK,
} led_pattern_t;

typedef struct {
    const char *name;
    int gpio_number;
    size_t led_count;
    led_pattern_t pattern;
    bool enabled;
    uint8_t *green_red_blue_frame;
    rmt_channel_handle_t transmit_channel;
    rmt_encoder_handle_t byte_encoder;
} external_led_string_t;

static external_led_string_t external_led_strings[EXTERNAL_LED_STRING_COUNT] = {
    {.name = "string-1", .gpio_number = CONFIG_LED_CONTROLLER_STRING_1_GPIO, .led_count = CONFIG_LED_CONTROLLER_STRING_1_LENGTH, .pattern = LED_PATTERN_SOLID, .enabled = false},
    {.name = "string-2", .gpio_number = CONFIG_LED_CONTROLLER_STRING_2_GPIO, .led_count = CONFIG_LED_CONTROLLER_STRING_2_LENGTH, .pattern = LED_PATTERN_CHASE, .enabled = false},
    {.name = "string-3", .gpio_number = CONFIG_LED_CONTROLLER_STRING_3_GPIO, .led_count = CONFIG_LED_CONTROLLER_STRING_3_LENGTH, .pattern = LED_PATTERN_RAINBOW, .enabled = false},
    {.name = "string-4", .gpio_number = CONFIG_LED_CONTROLLER_STRING_4_GPIO, .led_count = CONFIG_LED_CONTROLLER_STRING_4_LENGTH, .pattern = LED_PATTERN_BLINK, .enabled = false},
};

static const char *const pattern_names[] = {"solid", "chase", "rainbow", "blink"};
static SemaphoreHandle_t state_mutex;
static spi_device_handle_t onboard_led_spi_device;
// Power-up is deliberately dark. The web server can enable each external
// string independently and can set the onboard LED color after startup.
static onboard_led_color_t current_onboard_color = {.red = 0, .green = 0, .blue = 0};

static void set_frame_pixel(external_led_string_t *string, size_t pixel_index, uint8_t red, uint8_t green, uint8_t blue)
{
    const size_t byte_offset = pixel_index * 3;
    // WS2812-compatible LEDs use green-red-blue byte order on the wire.
    string->green_red_blue_frame[byte_offset] = green;
    string->green_red_blue_frame[byte_offset + 1] = red;
    string->green_red_blue_frame[byte_offset + 2] = blue;
}

static void color_wheel(uint8_t wheel_position, uint8_t *red, uint8_t *green, uint8_t *blue)
{
    if (wheel_position < 85) {
        *red = 31 - (wheel_position * 31 / 85);
        *green = wheel_position * 31 / 85;
        *blue = 0;
    } else if (wheel_position < 170) {
        wheel_position -= 85;
        *red = 0;
        *green = 31 - (wheel_position * 31 / 85);
        *blue = wheel_position * 31 / 85;
    } else {
        wheel_position -= 170;
        *red = wheel_position * 31 / 85;
        *green = 0;
        *blue = 31 - (wheel_position * 31 / 85);
    }
}

static void render_pattern(external_led_string_t *string, uint32_t frame_number)
{
    memset(string->green_red_blue_frame, 0, string->led_count * 3);
    if (!string->enabled) {
        return;
    }

    for (size_t pixel_index = 0; pixel_index < string->led_count; pixel_index++) {
        switch (string->pattern) {
            case LED_PATTERN_SOLID:
                set_frame_pixel(string, pixel_index, 24, 8, 2);
                break;
            case LED_PATTERN_CHASE:
                if (pixel_index == (frame_number / 2) % string->led_count) {
                    set_frame_pixel(string, pixel_index, 0, 24, 12);
                }
                break;
            case LED_PATTERN_RAINBOW: {
                uint8_t red;
                uint8_t green;
                uint8_t blue;
                color_wheel((uint8_t)((pixel_index * 256 / string->led_count + frame_number) & 0xff), &red, &green, &blue);
                set_frame_pixel(string, pixel_index, red, green, blue);
                break;
            }
            case LED_PATTERN_BLINK:
                if ((frame_number / 12) % 2 == 0) {
                    set_frame_pixel(string, pixel_index, 20, 0, 20);
                }
                break;
        }
    }
}

static esp_err_t initialize_external_string(external_led_string_t *string)
{
    string->green_red_blue_frame = calloc(string->led_count, 3);
    ESP_RETURN_ON_FALSE(string->green_red_blue_frame != NULL, ESP_ERR_NO_MEM, TAG, "Could not allocate frame for %s", string->name);

    const rmt_tx_channel_config_t channel_configuration = {
        .gpio_num = string->gpio_number,
        .clk_src = RMT_CLK_SRC_DEFAULT,
        .resolution_hz = ADDRESSABLE_LED_RMT_RESOLUTION_HZ,
        .mem_block_symbols = ADDRESSABLE_LED_RMT_MEMORY_SYMBOLS,
        .trans_queue_depth = 1,
        .intr_priority = 0,
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
    // The S3 has four RMT transmit channels and all four are reserved for the
    // external strings. SPI encodes each onboard WS2812 data bit into three
    // MOSI bits: 100 represents zero and 110 represents one at 2.4 MHz.
    const spi_bus_config_t bus_configuration = {
        .mosi_io_num = ONBOARD_ADDRESSABLE_LED_GPIO,
        .miso_io_num = -1,
        .sclk_io_num = -1,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
        .max_transfer_sz = 16,
    };
    const spi_device_interface_config_t device_configuration = {
        .clock_speed_hz = ONBOARD_SPI_CLOCK_HZ,
        .mode = 0,
        .spics_io_num = -1,
        .queue_size = 1,
    };
    ESP_RETURN_ON_ERROR(spi_bus_initialize(SPI2_HOST, &bus_configuration, SPI_DMA_DISABLED), TAG, "Could not initialize onboard LED SPI bus");
    return spi_bus_add_device(SPI2_HOST, &device_configuration, &onboard_led_spi_device);
}

esp_err_t led_controller_set_onboard_color(uint8_t red, uint8_t green, uint8_t blue)
{
    // The onboard addressable LED on this ESP32-S3 board uses RGB byte order.
    // This differs from the external WS2812 strings, which use GRB byte order
    // in set_frame_pixel(). Keeping these paths separate prevents correcting
    // the onboard color order from swapping colors on the external strings.
    const uint8_t red_green_blue[] = {red, green, blue};
    uint8_t encoded_data[9] = {0};
    size_t encoded_bit_index = 0;

    for (size_t byte_index = 0; byte_index < sizeof(red_green_blue); byte_index++) {
        for (int source_bit = 7; source_bit >= 0; source_bit--) {
            const uint8_t encoded_bits = (red_green_blue[byte_index] & (1U << source_bit)) ? 0x6 : 0x4;
            for (int encoded_bit = 2; encoded_bit >= 0; encoded_bit--) {
                if (encoded_bits & (1U << encoded_bit)) {
                    encoded_data[encoded_bit_index / 8] |= 1U << (7 - (encoded_bit_index % 8));
                }
                encoded_bit_index++;
            }
        }
    }

    spi_transaction_t transaction = {.length = sizeof(encoded_data) * 8, .tx_buffer = encoded_data};
    ESP_RETURN_ON_ERROR(spi_device_transmit(onboard_led_spi_device, &transaction), TAG, "Could not update onboard LED");
    vTaskDelay(pdMS_TO_TICKS(1));

    xSemaphoreTake(state_mutex, portMAX_DELAY);
    current_onboard_color = (onboard_led_color_t){.red = red, .green = green, .blue = blue};
    xSemaphoreGive(state_mutex);
    return ESP_OK;
}

static void led_pattern_task(void *task_parameter)
{
    (void)task_parameter;
    const rmt_transmit_config_t transmit_configuration = {.loop_count = 0, .flags.eot_level = 0, .flags.queue_nonblocking = 0};
    uint32_t frame_number = 0;

    while (true) {
        xSemaphoreTake(state_mutex, portMAX_DELAY);
        for (size_t string_index = 0; string_index < EXTERNAL_LED_STRING_COUNT; string_index++) {
            external_led_string_t *string = &external_led_strings[string_index];
            render_pattern(string, frame_number);
            ESP_ERROR_CHECK(rmt_transmit(string->transmit_channel, string->byte_encoder, string->green_red_blue_frame, string->led_count * 3, &transmit_configuration));
        }
        xSemaphoreGive(state_mutex);

        for (size_t string_index = 0; string_index < EXTERNAL_LED_STRING_COUNT; string_index++) {
            ESP_ERROR_CHECK(rmt_tx_wait_all_done(external_led_strings[string_index].transmit_channel, portMAX_DELAY));
        }
        frame_number++;
        vTaskDelay(pdMS_TO_TICKS(LED_PATTERN_FRAME_MILLISECONDS));
    }
}

esp_err_t led_controller_start(void)
{
    size_t configured_led_counts[EXTERNAL_LED_STRING_COUNT];
    ESP_RETURN_ON_ERROR(
        led_settings_load_counts(configured_led_counts),
        TAG,
        "Could not load LED string settings"
    );
    for (size_t string_index = 0; string_index < EXTERNAL_LED_STRING_COUNT; string_index++) {
        // Counts must be applied before initialize_external_string() allocates
        // its frame buffer. The buffer size and every RMT transmission length
        // then remain consistent for the lifetime of this boot.
        external_led_strings[string_index].led_count = configured_led_counts[string_index];
    }

    ESP_RETURN_ON_ERROR(
        led_settings_load_onboard_color(
            &current_onboard_color.red,
            &current_onboard_color.green,
            &current_onboard_color.blue
        ),
        TAG,
        "Could not load onboard LED colour setting"
    );

    state_mutex = xSemaphoreCreateMutex();
    ESP_RETURN_ON_FALSE(state_mutex != NULL, ESP_ERR_NO_MEM, TAG, "Could not create LED state mutex");
    ESP_RETURN_ON_ERROR(initialize_onboard_led(), TAG, "Could not initialize onboard LED");
    ESP_RETURN_ON_ERROR(led_controller_set_onboard_color(current_onboard_color.red, current_onboard_color.green, current_onboard_color.blue), TAG, "Could not set initial onboard color");

    for (size_t string_index = 0; string_index < EXTERNAL_LED_STRING_COUNT; string_index++) {
        ESP_RETURN_ON_ERROR(initialize_external_string(&external_led_strings[string_index]), TAG, "Could not initialize external string %u", (unsigned)string_index);
    }

    BaseType_t task_created = xTaskCreatePinnedToCore(led_pattern_task, "led-patterns", LED_PATTERN_TASK_STACK_SIZE, NULL, LED_PATTERN_TASK_PRIORITY, NULL, LED_PATTERN_TASK_CORE);
    ESP_RETURN_ON_FALSE(task_created == pdPASS, ESP_ERR_NO_MEM, TAG, "Could not create LED pattern task");
    ESP_LOGI(TAG, "LED pattern task started on core %d", LED_PATTERN_TASK_CORE);
    return ESP_OK;
}

esp_err_t led_controller_set_external_enabled(size_t string_index, bool enabled)
{
    ESP_RETURN_ON_FALSE(string_index < EXTERNAL_LED_STRING_COUNT, ESP_ERR_INVALID_ARG, TAG, "Invalid LED string index");
    xSemaphoreTake(state_mutex, portMAX_DELAY);
    external_led_strings[string_index].enabled = enabled;
    xSemaphoreGive(state_mutex);
    return ESP_OK;
}

void led_controller_get_state(external_led_string_state_t strings[EXTERNAL_LED_STRING_COUNT], onboard_led_color_t *onboard_color)
{
    xSemaphoreTake(state_mutex, portMAX_DELAY);
    for (size_t index = 0; index < EXTERNAL_LED_STRING_COUNT; index++) {
        strings[index] = (external_led_string_state_t){
            .enabled = external_led_strings[index].enabled,
            .led_count = external_led_strings[index].led_count,
            .pattern_name = pattern_names[external_led_strings[index].pattern],
        };
    }
    *onboard_color = current_onboard_color;
    xSemaphoreGive(state_mutex);
}
