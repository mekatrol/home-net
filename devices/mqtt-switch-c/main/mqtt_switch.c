#include "mqtt_switch.h"

#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#include "app_state.h"
#include "esp_event.h"
#include "esp_idf_version.h"
#include "esp_log.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "mqtt_client.h"
#include "sdkconfig.h"

#define MQTT_KEEPALIVE_STATUS_PERIOD_MS 30000
#define MQTT_INACTIVITY_CHECK_MS 1000

static const char *TAG = "mqtt-switch-mqtt";

static esp_mqtt_client_handle_t mqtt_client;

static bool parse_json_bool_field(const char *payload, int payload_length, const char *field_name, bool *value)
{
    char quoted_field[32];
    snprintf(quoted_field, sizeof(quoted_field), "\"%s\"", field_name);

    const char *payload_end = payload + payload_length;
    const char *field = strstr(payload, quoted_field);
    if (field == NULL || field >= payload_end) {
        return false;
    }

    const char *cursor = field + strlen(quoted_field);
    while (cursor < payload_end && (*cursor == ' ' || *cursor == '\t' || *cursor == '\r' || *cursor == '\n')) {
        cursor++;
    }

    if (cursor >= payload_end || *cursor != ':') {
        return false;
    }

    cursor++;
    while (cursor < payload_end && (*cursor == ' ' || *cursor == '\t' || *cursor == '\r' || *cursor == '\n')) {
        cursor++;
    }

    if (payload_end - cursor >= 4 && strncmp(cursor, "true", 4) == 0) {
        *value = true;
        return true;
    }

    if (payload_end - cursor >= 5 && strncmp(cursor, "false", 5) == 0) {
        *value = false;
        return true;
    }

    return false;
}

void mqtt_switch_mqtt_publish_status(void)
{
    mqtt_switch_state_t *state = mqtt_switch_state();

    if (mqtt_client == NULL) {
        return;
    }

    char status[48];
    snprintf(
        status,
        sizeof(status),
        "{\"enabled\": %s, \"on\": %s}",
        state->output_enabled ? "true" : "false",
        state->output_on ? "true" : "false"
    );

    esp_mqtt_client_publish(mqtt_client, CONFIG_MQTT_SWITCH_STATUS_TOPIC, status, 0, 0, 0);
}

static void handle_mqtt_command(const char *payload, int payload_length)
{
    mqtt_switch_state_t *state = mqtt_switch_state();
    bool parsed_any_field = false;
    bool parsed_value = false;

    if (parse_json_bool_field(payload, payload_length, "enabled", &parsed_value)) {
        state->output_enabled = parsed_value;
        parsed_any_field = true;
    }

    if (parse_json_bool_field(payload, payload_length, "on", &parsed_value)) {
        state->output_on = parsed_value;
        parsed_any_field = true;
    }

    if (!parsed_any_field) {
        ESP_LOGW(TAG, "Invalid MQTT JSON: %.*s", payload_length, payload);
        return;
    }
    mqtt_switch_mqtt_publish_status();
}

static void mqtt_event_handler(void *handler_args, esp_event_base_t base, int32_t event_id, void *event_data)
{
    mqtt_switch_state_t *state = mqtt_switch_state();
    esp_mqtt_event_handle_t event = event_data;

    switch ((esp_mqtt_event_id_t)event_id) {
    case MQTT_EVENT_CONNECTED:
        ESP_LOGI(TAG, "MQTT connected");
        xEventGroupSetBits(state->connection_event_group, MQTT_SWITCH_MQTT_CONNECTED_BIT);
        state->last_mqtt_rx_ms = mqtt_switch_now_ms();
        esp_mqtt_client_subscribe(mqtt_client, CONFIG_MQTT_SWITCH_SET_TOPIC, 0);
        mqtt_switch_mqtt_publish_status();
        break;

    case MQTT_EVENT_DISCONNECTED:
        ESP_LOGW(TAG, "MQTT disconnected");
        xEventGroupClearBits(state->connection_event_group, MQTT_SWITCH_MQTT_CONNECTED_BIT);
        break;

    case MQTT_EVENT_DATA:
        state->last_mqtt_rx_ms = mqtt_switch_now_ms();
        state->last_mqtt_indicator_ms = state->last_mqtt_rx_ms;
        handle_mqtt_command(event->data, event->data_len);
        break;

    case MQTT_EVENT_ERROR:
        ESP_LOGW(TAG, "MQTT error");
        xEventGroupClearBits(state->connection_event_group, MQTT_SWITCH_MQTT_CONNECTED_BIT);
        break;

    default:
        break;
    }
}

void mqtt_switch_mqtt_start(void)
{
    if (mqtt_client != NULL) {
        return;
    }

#if ESP_IDF_VERSION >= ESP_IDF_VERSION_VAL(5, 0, 0)
    esp_mqtt_client_config_t mqtt_config = {
        .broker.address.uri = CONFIG_MQTT_SWITCH_BROKER_URI,
        .credentials.client_id = CONFIG_MQTT_SWITCH_CLIENT_ID,
        .credentials.username = CONFIG_MQTT_SWITCH_USERNAME,
        .credentials.authentication.password = CONFIG_MQTT_SWITCH_PASSWORD,
        .session.keepalive = 60,
    };
#else
    esp_mqtt_client_config_t mqtt_config = {
        .uri = CONFIG_MQTT_SWITCH_BROKER_URI,
        .client_id = CONFIG_MQTT_SWITCH_CLIENT_ID,
        .username = CONFIG_MQTT_SWITCH_USERNAME,
        .password = CONFIG_MQTT_SWITCH_PASSWORD,
        .keepalive = 60,
    };
#endif

    mqtt_client = esp_mqtt_client_init(&mqtt_config);
    ESP_ERROR_CHECK(esp_mqtt_client_register_event(mqtt_client, ESP_EVENT_ANY_ID, mqtt_event_handler, NULL));
    ESP_ERROR_CHECK(esp_mqtt_client_start(mqtt_client));
}

static void keepalive_status_task(void *arg)
{
    mqtt_switch_state_t *state = mqtt_switch_state();

    while (true) {
        EventBits_t bits = xEventGroupGetBits(state->connection_event_group);
        if (bits & MQTT_SWITCH_MQTT_CONNECTED_BIT) {
            mqtt_switch_mqtt_publish_status();
        }

        vTaskDelay(pdMS_TO_TICKS(MQTT_KEEPALIVE_STATUS_PERIOD_MS));
    }
}

static void mqtt_inactivity_watchdog_task(void *arg)
{
    mqtt_switch_state_t *state = mqtt_switch_state();

    while (true) {
        if (state->last_mqtt_rx_ms > 0) {
            int64_t idle_ms = mqtt_switch_now_ms() - state->last_mqtt_rx_ms;
            if (idle_ms > CONFIG_MQTT_SWITCH_MQTT_INACTIVITY_TIMEOUT_SECONDS * 1000LL) {
                ESP_LOGE(TAG, "MQTT inactivity timeout, restarting");
                vTaskDelay(pdMS_TO_TICKS(1000));
                esp_restart();
            }
        }

        vTaskDelay(pdMS_TO_TICKS(MQTT_INACTIVITY_CHECK_MS));
    }
}

void mqtt_switch_mqtt_start_tasks(void)
{
    xTaskCreate(keepalive_status_task, "keepalive_status", 4096, NULL, 4, NULL);
    xTaskCreate(mqtt_inactivity_watchdog_task, "mqtt_watchdog", 4096, NULL, 4, NULL);
}
