#pragma once

#include "esp_err.h"

typedef esp_err_t (*network_ready_callback_t)(void);

esp_err_t led_controller_wifi_start(network_ready_callback_t network_ready_callback);
