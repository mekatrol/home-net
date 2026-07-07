#pragma once

#include <stdint.h>

void mqtt_switch_status_led_configure(void);
void mqtt_switch_status_led_set(uint8_t red, uint8_t green, uint8_t blue);
void mqtt_switch_status_led_flash_startup(void);
