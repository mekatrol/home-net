#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"

#define MQTT_SWITCH_WIFI_CONNECTED_BIT BIT0
#define MQTT_SWITCH_MQTT_CONNECTED_BIT BIT1

typedef struct {
    EventGroupHandle_t connection_event_group;
    bool output_enabled;
    bool output_on;
    int64_t last_mqtt_rx_ms;
    int64_t last_mqtt_indicator_ms;
} mqtt_switch_state_t;

int64_t mqtt_switch_now_ms(void);
mqtt_switch_state_t *mqtt_switch_state(void);
