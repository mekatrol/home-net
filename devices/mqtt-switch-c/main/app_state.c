#include "app_state.h"

#include "esp_timer.h"

static mqtt_switch_state_t state;

int64_t mqtt_switch_now_ms(void)
{
    return esp_timer_get_time() / 1000;
}

mqtt_switch_state_t *mqtt_switch_state(void)
{
    return &state;
}
