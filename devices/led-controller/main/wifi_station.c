#include "wifi_station.h"

#include <string.h>

#include "esp_check.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_netif_ip_addr.h"
#include "esp_wifi.h"
#include "sdkconfig.h"

static const char *TAG = "led-wifi";
static network_ready_callback_t ready_callback;
static bool network_service_started;

static void handle_wifi_event(void *argument, esp_event_base_t event_base, int32_t event_id, void *event_data)
{
    (void)argument;
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        ESP_ERROR_CHECK(esp_wifi_connect());
    } else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        ESP_LOGW(TAG, "Wi-Fi disconnected; reconnecting");
        ESP_ERROR_CHECK(esp_wifi_connect());
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        const ip_event_got_ip_t *event = event_data;
        ESP_LOGI(TAG, "Wi-Fi connected, open http://" IPSTR "/", IP2STR(&event->ip_info.ip));
        if (!network_service_started) {
            char controller_ip_address[16];
            esp_ip4addr_ntoa(&event->ip_info.ip, controller_ip_address, sizeof(controller_ip_address));
            ESP_ERROR_CHECK(ready_callback(controller_ip_address));
            network_service_started = true;
        }
    }
}

esp_err_t led_controller_wifi_start(network_ready_callback_t network_ready_callback)
{
    if (strlen(CONFIG_LED_CONTROLLER_WIFI_SSID) == 0) {
        ESP_LOGE(
            TAG,
            "Wi-Fi SSID is empty. Set it under 'LED controller' in menuconfig, then rebuild and flash"
        );
        return ESP_ERR_INVALID_ARG;
    }

    ready_callback = network_ready_callback;
    ESP_RETURN_ON_ERROR(esp_netif_init(), TAG, "Could not initialize TCP/IP stack");
    ESP_RETURN_ON_ERROR(esp_event_loop_create_default(), TAG, "Could not create event loop");
    ESP_RETURN_ON_FALSE(esp_netif_create_default_wifi_sta() != NULL, ESP_FAIL, TAG, "Could not create Wi-Fi station interface");

    wifi_init_config_t initialization_configuration = WIFI_INIT_CONFIG_DEFAULT();
    ESP_RETURN_ON_ERROR(esp_wifi_init(&initialization_configuration), TAG, "Could not initialize Wi-Fi");
    ESP_RETURN_ON_ERROR(esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID, handle_wifi_event, NULL, NULL), TAG, "Could not register Wi-Fi handler");
    ESP_RETURN_ON_ERROR(esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP, handle_wifi_event, NULL, NULL), TAG, "Could not register IP handler");

    wifi_config_t station_configuration = {.sta = {
        .ssid = CONFIG_LED_CONTROLLER_WIFI_SSID,
        .password = CONFIG_LED_CONTROLLER_WIFI_PASSWORD,
        // An empty password is valid for an intentionally open access point.
        // Otherwise reject networks weaker than WPA2 Personal.
        .threshold.authmode = sizeof(CONFIG_LED_CONTROLLER_WIFI_PASSWORD) > 1
            ? WIFI_AUTH_WPA2_PSK
            : WIFI_AUTH_OPEN,
    }};
    ESP_RETURN_ON_ERROR(esp_wifi_set_mode(WIFI_MODE_STA), TAG, "Could not set station mode");
    ESP_RETURN_ON_ERROR(esp_wifi_set_config(WIFI_IF_STA, &station_configuration), TAG, "Could not configure Wi-Fi station");
    return esp_wifi_start();
}
