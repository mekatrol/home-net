idf_component_register(
    SRCS
        "app_state.c"
        "main.c"
        "mqtt_switch.c"
        "status_led.c"
        "switch_output.c"
        "wifi_station.c"
    INCLUDE_DIRS "."
    REQUIRES
        esp_driver_gpio
        esp_event
        esp_netif
        esp_wifi
        mqtt
        nvs_flash
)
