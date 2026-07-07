#include "wifi_station.h"

#include "app_state.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_netif_ip_addr.h"
#include "esp_wifi.h"
#include "mqtt_switch.h"
#include "sdkconfig.h"

static const char *TAG = "mqtt-switch-wifi";

static void wifi_event_handler(void *handler_args, esp_event_base_t event_base, int32_t event_id, void *event_data)
{
    mqtt_switch_state_t *state = mqtt_switch_state();

    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        ESP_ERROR_CHECK(esp_wifi_connect());
        return;
    }

    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        ESP_LOGW(TAG, "Wi-Fi disconnected, reconnecting");
        xEventGroupClearBits(
            state->connection_event_group,
            MQTT_SWITCH_WIFI_CONNECTED_BIT | MQTT_SWITCH_MQTT_CONNECTED_BIT
        );
        ESP_ERROR_CHECK(esp_wifi_connect());
        return;
    }

    if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *event = event_data;
        ESP_LOGI(TAG, "Wi-Fi connected, IP " IPSTR, IP2STR(&event->ip_info.ip));
        xEventGroupSetBits(state->connection_event_group, MQTT_SWITCH_WIFI_CONNECTED_BIT);
        mqtt_switch_mqtt_start();
    }
}

void mqtt_switch_wifi_start(void)
{
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t init_config = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init_config));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event_handler, NULL, NULL));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event_handler, NULL, NULL));

    wifi_config_t wifi_config = {
        .sta = {
            .ssid = CONFIG_MQTT_SWITCH_WIFI_SSID,
            .password = CONFIG_MQTT_SWITCH_WIFI_PASSWORD,
            .threshold.authmode = WIFI_AUTH_WPA2_PSK,
        },
    };

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());
}
