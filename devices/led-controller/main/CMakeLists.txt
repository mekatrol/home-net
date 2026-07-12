idf_component_register(
    SRCS
        "led_controller.c"
        "led_settings.c"
        "main.c"
        "web_server.c"
        "wifi_station.c"
    INCLUDE_DIRS "."
    REQUIRES
        esp_driver_rmt
        esp_driver_spi
        esp_event
        esp_http_server
        esp_netif
        esp_wifi
        nvs_flash
)
