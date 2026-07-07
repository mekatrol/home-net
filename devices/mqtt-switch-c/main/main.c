#include "app_state.h"
#include "esp_err.h"
#include "freertos/event_groups.h"
#include "mqtt_switch.h"
#include "nvs_flash.h"
#include "status_led.h"
#include "switch_output.h"
#include "wifi_station.h"

static void initialize_nvs(void)
{
    esp_err_t nvs_result = nvs_flash_init();
    if (nvs_result == ESP_ERR_NVS_NO_FREE_PAGES || nvs_result == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        nvs_result = nvs_flash_init();
    }
    ESP_ERROR_CHECK(nvs_result);
}

void app_main(void)
{
    mqtt_switch_state_t *state = mqtt_switch_state();

    initialize_nvs();

    state->connection_event_group = xEventGroupCreate();
    mqtt_switch_output_configure();
    mqtt_switch_status_led_configure();
    mqtt_switch_status_led_flash_startup();
    mqtt_switch_wifi_start();

    mqtt_switch_output_start_task();
    mqtt_switch_mqtt_start_tasks();
}
