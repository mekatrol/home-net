#include "status_led.h"

#include "driver/gpio.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sdkconfig.h"

#define STARTUP_FLASH_INTERVAL_MS 200

#ifndef CONFIG_MQTT_SWITCH_STATUS_LED_ACTIVE_LEVEL
#define CONFIG_MQTT_SWITCH_STATUS_LED_ACTIVE_LEVEL 0
#endif

static const char *TAG = "mqtt-switch-led";

static int status_led_level_for_state(bool enabled)
{
    if (enabled) {
        return CONFIG_MQTT_SWITCH_STATUS_LED_ACTIVE_LEVEL;
    }

    return CONFIG_MQTT_SWITCH_STATUS_LED_ACTIVE_LEVEL == 0 ? 1 : 0;
}

void mqtt_switch_status_led_set(bool enabled)
{
    /*
     * The Wemos ESP32-S2 Mini status LED is wired as a single GPIO indicator. 
     * Some dev-board LEDs are active-low because
     * the GPIO pin sinks current through the LED, so the active level is kept
     * in Kconfig instead of assuming that logical "on" always means GPIO high.
     */
    ESP_ERROR_CHECK(gpio_set_level(CONFIG_MQTT_SWITCH_STATUS_LED_GPIO, status_led_level_for_state(enabled)));
}

void mqtt_switch_status_led_configure(void)
{
    gpio_config_t led_config = {
        .pin_bit_mask = 1ULL << CONFIG_MQTT_SWITCH_STATUS_LED_GPIO,
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };

    ESP_LOGI(
        TAG,
        "Configuring status LED on GPIO%d active level %d",
        CONFIG_MQTT_SWITCH_STATUS_LED_GPIO,
        CONFIG_MQTT_SWITCH_STATUS_LED_ACTIVE_LEVEL
    );
    ESP_ERROR_CHECK(gpio_config(&led_config));
    mqtt_switch_status_led_set(false);
}

void mqtt_switch_status_led_flash_startup(void)
{
    for (int i = 0; i < 2; i++) {
        mqtt_switch_status_led_set(true);
        vTaskDelay(pdMS_TO_TICKS(STARTUP_FLASH_INTERVAL_MS));
        mqtt_switch_status_led_set(false);
        vTaskDelay(pdMS_TO_TICKS(STARTUP_FLASH_INTERVAL_MS));
    }
}
