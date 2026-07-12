#pragma once

#include "esp_err.h"

/** Starts a background fetch of the sequence document for this controller. */
esp_err_t led_sequence_api_fetch(const char *controller_ip_address);
