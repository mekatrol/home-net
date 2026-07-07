#include "switch_output.h"

#include <stdbool.h>

#include "app_state.h"
#include "driver/gpio.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sdkconfig.h"
#include "status_led.h"

#define OUTPUT_CONTROL_PERIOD_MS 100
#define MQTT_INACTIVE_FLASH_HZ 2
#define MQTT_RX_INDICATOR_MS 1000

static const char *TAG = "mqtt-switch-output";

static void output_control_task(void *arg)
{
    mqtt_switch_state_t *state = mqtt_switch_state();

    while (true) {
        int64_t current_ms = mqtt_switch_now_ms();
        bool rx_indicator_active = state->last_mqtt_indicator_ms > 0 &&
            current_ms - state->last_mqtt_indicator_ms < MQTT_RX_INDICATOR_MS;
        bool inactivity_warning_active = state->last_mqtt_rx_ms > 0 &&
            current_ms - state->last_mqtt_rx_ms >= CONFIG_MQTT_SWITCH_MQTT_INACTIVITY_WARNING_SECONDS * 1000LL;

        if (rx_indicator_active) {
            mqtt_switch_status_led_set(0, 1, 0);
        } else if (inactivity_warning_active) {
            /*
             * A 2 Hz blink has a 500 ms full cycle: 250 ms on, 250 ms off.
             * Dividing uptime by the phase length gives a stable phase number
             * without storing extra blink state.
             */
            int flash_phase_ms = 1000 / (MQTT_INACTIVE_FLASH_HZ * 2);
            bool flash_on = ((current_ms / flash_phase_ms) % 2) == 0;
            mqtt_switch_status_led_set(0, flash_on ? 1 : 0, 0);
        } else {
            mqtt_switch_status_led_set(0, 0, 0);
        }

        gpio_set_level(CONFIG_MQTT_SWITCH_OUTPUT_GPIO, state->output_enabled && state->output_on);
        vTaskDelay(pdMS_TO_TICKS(OUTPUT_CONTROL_PERIOD_MS));
    }
}

void mqtt_switch_output_configure(void)
{
    gpio_config_t output_config = {
        .pin_bit_mask = 1ULL << CONFIG_MQTT_SWITCH_OUTPUT_GPIO,
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };

    ESP_LOGI(TAG, "Configuring switch output on GPIO%d", CONFIG_MQTT_SWITCH_OUTPUT_GPIO);
    ESP_ERROR_CHECK(gpio_config(&output_config));
    gpio_set_level(CONFIG_MQTT_SWITCH_OUTPUT_GPIO, 0);
}

void mqtt_switch_output_start_task(void)
{
    xTaskCreate(output_control_task, "output_control", 4096, NULL, 5, NULL);
}
