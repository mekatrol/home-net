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

    /*
     * This task is the only place that continuously drives the physical
     * switch output and the status LED pattern. MQTT callbacks update the
     * shared state when commands arrive, then this periodic loop turns that
     * state into GPIO levels. Keeping GPIO writes here makes the output
     * behavior predictable even if MQTT traffic arrives in short bursts.
     */
    while (true) {
        int64_t current_ms = mqtt_switch_now_ms();

        /*
         * A recently received MQTT command gets a short solid LED indication
         * so there is visible feedback that the device is still hearing the
         * broker. This is intentionally time-based rather than message-count
         * based so repeated messages simply extend the visible activity window.
         */
        bool rx_indicator_active = state->last_mqtt_indicator_ms > 0 &&
            current_ms - state->last_mqtt_indicator_ms < MQTT_RX_INDICATOR_MS;

        /*
         * The inactivity warning is separate from the hard watchdog restart in
         * mqtt_inactivity_watchdog_task(). It gives a local visual warning
         * before the timeout path resets the chip, which helps diagnose broker
         * or Wi-Fi issues without needing serial logs.
         */
        bool inactivity_warning_active = state->last_mqtt_rx_ms > 0 &&
            current_ms - state->last_mqtt_rx_ms >= CONFIG_MQTT_SWITCH_MQTT_INACTIVITY_WARNING_SECONDS * 1000LL;

        /*
         * LED priority is: newest MQTT activity first, inactivity warning
         * second, otherwise off. The activity pulse wins so a live command is
         * never hidden behind an older inactivity blink.
         */
        if (rx_indicator_active) {
            mqtt_switch_status_led_set(true);
        } else if (inactivity_warning_active) {
            /*
             * A 2 Hz blink has a 500 ms full cycle: 250 ms on, 250 ms off.
             * Dividing uptime by the phase length gives a stable phase number
             * without storing extra blink state.
             */
            int flash_phase_ms = 1000 / (MQTT_INACTIVE_FLASH_HZ * 2);
            bool flash_on = ((current_ms / flash_phase_ms) % 2) == 0;
            mqtt_switch_status_led_set(flash_on);
        } else {
            mqtt_switch_status_led_set(false);
        }

        /*
         * The output is gated by both "enabled" and "on". "enabled" is a
         * higher-level safety/arming flag, while "on" is the requested relay
         * state. Requiring both prevents an old "on" command from energizing
         * the output as soon as the device is re-enabled.
         */
        gpio_set_level(CONFIG_MQTT_SWITCH_OUTPUT_GPIO, state->output_enabled && state->output_on);

        /*
         * A 100 ms period is fast enough for human-visible LED feedback and
         * switch control, but slow enough that this low-priority housekeeping
         * loop does not waste CPU while the networking stack is active.
         */
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
    /*
     * The output task has a slightly higher priority than the MQTT status
     * tasks because it performs the local hardware action that reflects the
     * most recent command. It still yields every cycle, so Wi-Fi and MQTT
     * event handling can run normally.
     */
    xTaskCreate(output_control_task, "output_control", 4096, NULL, 5, NULL);
}
