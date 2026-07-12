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

#define ONBOARD_ADDRESSABLE_LED_GPIO 21
#define ADDRESSABLE_LED_RMT_RESOLUTION_HZ 10000000
#define ADDRESSABLE_LED_RMT_MEMORY_SYMBOLS 48
#define PLAYBACK_SCHEDULER_TICK_MILLISECONDS 10
#define LED_PATTERN_TASK_STACK_SIZE 6144
#define LED_PATTERN_TASK_PRIORITY 5
#define LED_PATTERN_TASK_CORE 1
#define ONBOARD_SPI_CLOCK_HZ 2400000

static const char *TAG = "led-controller";

typedef struct {
    const char *name;
    int gpio_number;
    size_t led_count;
    bool enabled;
    size_t bytes_per_led;
    size_t sequence_count;
    uint8_t *sequence_bytes;
    uint32_t sequence_interval_milliseconds;
    size_t next_sequence_index;
    TickType_t last_sequence_tick;
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
static uint8_t *onboard_sequence_bytes;
static size_t onboard_sequence_count;
static uint32_t onboard_sequence_interval_milliseconds;
static size_t next_onboard_sequence_index;
static TickType_t last_onboard_sequence_tick;
// Power-up is deliberately dark. The web server can enable each external
// string independently and can set the onboard LED color after startup.
static onboard_led_color_t current_onboard_color = {.red = 0, .green = 0, .blue = 0};

static esp_err_t initialize_external_string(external_led_string_t *string)
{
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

static esp_err_t write_onboard_color(uint8_t red, uint8_t green, uint8_t blue)
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

    return ESP_OK;
}

esp_err_t led_controller_set_onboard_color(uint8_t red, uint8_t green, uint8_t blue)
{
    ESP_RETURN_ON_ERROR(write_onboard_color(red, green, blue), TAG, "Could not set onboard LED color");
    xSemaphoreTake(state_mutex, portMAX_DELAY);
    current_onboard_color = (onboard_led_color_t){.red = red, .green = green, .blue = blue};
    xSemaphoreGive(state_mutex);
    return ESP_OK;
}

static void led_pattern_task(void *task_parameter)
{
    (void)task_parameter;
    const rmt_transmit_config_t transmit_configuration = {.loop_count = 0, .flags.eot_level = 0, .flags.queue_nonblocking = 0};

    while (true) {
        const TickType_t current_tick = xTaskGetTickCount();
        bool string_transmitted[EXTERNAL_LED_STRING_COUNT] = {false};
        xSemaphoreTake(state_mutex, portMAX_DELAY);

        if (onboard_sequence_count > 0 &&
            current_tick - last_onboard_sequence_tick >= pdMS_TO_TICKS(onboard_sequence_interval_milliseconds)) {
            const uint8_t *color = onboard_sequence_bytes + next_onboard_sequence_index * 3;
            ESP_ERROR_CHECK(write_onboard_color(color[0], color[1], color[2]));
            current_onboard_color = (onboard_led_color_t){.red = color[0], .green = color[1], .blue = color[2]};
            next_onboard_sequence_index = (next_onboard_sequence_index + 1) % onboard_sequence_count;
            last_onboard_sequence_tick = current_tick;
        }

        for (size_t string_index = 0; string_index < EXTERNAL_LED_STRING_COUNT; string_index++) {
            external_led_string_t *string = &external_led_strings[string_index];
            if (!string->enabled || string->sequence_count == 0 ||
                current_tick - string->last_sequence_tick < pdMS_TO_TICKS(string->sequence_interval_milliseconds)) {
                continue;
            }
            const size_t frame_size = string->led_count * string->bytes_per_led;
            ESP_ERROR_CHECK(rmt_transmit(string->transmit_channel, string->byte_encoder, string->sequence_bytes + string->next_sequence_index * frame_size, frame_size, &transmit_configuration));
            string->next_sequence_index = (string->next_sequence_index + 1) % string->sequence_count;
            string->last_sequence_tick = current_tick;
            string_transmitted[string_index] = true;
        }
        // RMT reads directly from the selected sequence buffer. Keep the
        // mutex until every channel is finished so an API refresh cannot free
        // and replace a buffer while the peripheral is still consuming it.
        for (size_t string_index = 0; string_index < EXTERNAL_LED_STRING_COUNT; string_index++) {
            if (string_transmitted[string_index]) {
                ESP_ERROR_CHECK(rmt_tx_wait_all_done(external_led_strings[string_index].transmit_channel, portMAX_DELAY));
            }
        }
        xSemaphoreGive(state_mutex);
        vTaskDelay(pdMS_TO_TICKS(PLAYBACK_SCHEDULER_TICK_MILLISECONDS));
    }
}

esp_err_t led_controller_apply_onboard_sequences(
    const onboard_led_sequence_configuration_t *configuration,
    uint32_t sequence_interval_milliseconds
)
{
    ESP_RETURN_ON_FALSE(configuration != NULL && configuration->sequence_count > 0 && configuration->red_green_blue_sequence_bytes != NULL, ESP_ERR_INVALID_ARG, TAG, "Invalid onboard sequence configuration");
    ESP_RETURN_ON_FALSE(sequence_interval_milliseconds > 0, ESP_ERR_INVALID_ARG, TAG, "Onboard sequence interval must be positive");
    uint8_t *sequence_copy = malloc(configuration->sequence_count * 3);
    ESP_RETURN_ON_FALSE(sequence_copy != NULL, ESP_ERR_NO_MEM, TAG, "Could not allocate onboard sequence data");
    memcpy(sequence_copy, configuration->red_green_blue_sequence_bytes, configuration->sequence_count * 3);

    xSemaphoreTake(state_mutex, portMAX_DELAY);
    free(onboard_sequence_bytes);
    onboard_sequence_bytes = sequence_copy;
    onboard_sequence_count = configuration->sequence_count;
    onboard_sequence_interval_milliseconds = sequence_interval_milliseconds;
    next_onboard_sequence_index = 0;
    last_onboard_sequence_tick = xTaskGetTickCount() - pdMS_TO_TICKS(sequence_interval_milliseconds);
    xSemaphoreGive(state_mutex);
    return ESP_OK;
}

esp_err_t led_controller_start(void)
{
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

esp_err_t led_controller_apply_external_sequences(
    size_t string_index,
    const external_led_sequence_configuration_t *configuration,
    uint32_t sequence_interval_milliseconds
)
{
    ESP_RETURN_ON_FALSE(string_index < EXTERNAL_LED_STRING_COUNT && configuration != NULL, ESP_ERR_INVALID_ARG, TAG, "Invalid sequence configuration");
    ESP_RETURN_ON_FALSE(configuration->led_count > 0 && configuration->sequence_count > 0, ESP_ERR_INVALID_ARG, TAG, "An active string needs at least one LED and sequence");
    ESP_RETURN_ON_FALSE(configuration->bytes_per_led == 3 || configuration->bytes_per_led == 4, ESP_ERR_INVALID_ARG, TAG, "LED pixels must contain three or four bytes");
    ESP_RETURN_ON_FALSE(sequence_interval_milliseconds > 0, ESP_ERR_INVALID_ARG, TAG, "Sequence interval must be positive");

    const size_t allocation_size = configuration->led_count * configuration->bytes_per_led * configuration->sequence_count;
    uint8_t *sequence_copy = malloc(allocation_size);
    ESP_RETURN_ON_FALSE(sequence_copy != NULL, ESP_ERR_NO_MEM, TAG, "Could not allocate sequence data for string %u", (unsigned)(string_index + 1));
    memcpy(sequence_copy, configuration->sequence_bytes, allocation_size);

    xSemaphoreTake(state_mutex, portMAX_DELAY);
    external_led_string_t *string = &external_led_strings[string_index];
    free(string->sequence_bytes);
    string->sequence_bytes = sequence_copy;
    string->led_count = configuration->led_count;
    string->bytes_per_led = configuration->bytes_per_led;
    string->sequence_count = configuration->sequence_count;
    string->sequence_interval_milliseconds = sequence_interval_milliseconds;
    string->next_sequence_index = 0;
    string->last_sequence_tick = xTaskGetTickCount() - pdMS_TO_TICKS(sequence_interval_milliseconds);
    string->enabled = true;
    xSemaphoreGive(state_mutex);
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
            .pattern_name = "api-sequence",
        };
    }
    *onboard_color = current_onboard_color;
    xSemaphoreGive(state_mutex);
}
