#pragma once

#include <stdbool.h>

void mqtt_switch_status_led_configure(void);
void mqtt_switch_status_led_set(bool enabled);
void mqtt_switch_status_led_flash_startup(void);
