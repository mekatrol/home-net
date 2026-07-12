#include "esp_check.h"
#include "esp_log.h"
#include "nvs_flash.h"

#include "led_controller.h"
#include "web_server.h"
#include "wifi_station.h"

static const char *TAG = "led-controller-main";

static void initialize_nonvolatile_storage(void)
{
    esp_err_t initialization_result = nvs_flash_init();
    if (initialization_result == ESP_ERR_NVS_NO_FREE_PAGES ||
        initialization_result == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        initialization_result = nvs_flash_init();
    }
    ESP_ERROR_CHECK(initialization_result);
}

void app_main(void)
{
    initialize_nonvolatile_storage();

    // The LED task is explicitly pinned to core 1. RMT (Remote Control
    // Transceiver) generates each addressable-LED waveform in hardware after
    // the task queues a frame, so pattern calculation cannot disturb timing.
    ESP_ERROR_CHECK(led_controller_start());

    // ESP-IDF pins its Wi-Fi driver to core 0 for this target. The HTTP server
    // is also pinned there by web_server_start(), keeping network work away
    // from pattern calculation on core 1.
    const esp_err_t wifi_start_result = led_controller_wifi_start(web_server_start);
    if (wifi_start_result != ESP_OK) {
        // Keep the LED task alive when network configuration is missing. This
        // makes the configuration error readable in the serial monitor instead
        // of repeatedly rebooting before the user can diagnose it.
        ESP_LOGE(TAG, "Wi-Fi did not start: %s", esp_err_to_name(wifi_start_result));
    }
}
