#include "web_server.h"

#include <stdlib.h>
#include <string.h>

#include "esp_check.h"
#include "esp_http_server.h"
#include "led_controller.h"

static const char INDEX_HTML[] =
    "<!doctype html><meta name=viewport content='width=device-width'><title>LED controller</title>"
    "<style>body{font:18px sans-serif;max-width:42rem;margin:2rem auto;padding:0 1rem}button,input{font:inherit;margin:.3rem}section{padding:1rem;border:1px solid #aaa;margin:1rem 0}</style>"
    "<h1>LED controller</h1><section id=strings></section>"
    "<section><h2>Onboard LED</h2><input id=color type=color value=#080808><button onclick=setColor()>Set colour</button></section>"
    "<script>async function refresh(){let s=await(await fetch('/api/state')).json();strings.innerHTML=s.strings.map((x,i)=>`<p>String ${i+1}: ${x.length} LEDs, ${x.pattern} <button onclick=toggle(${i},${!x.enabled})>${x.enabled?'Turn off':'Turn on'}</button></p>`).join('');color.value='#'+[s.onboard.red,s.onboard.green,s.onboard.blue].map(x=>x.toString(16).padStart(2,'0')).join('')}"
    "async function toggle(i,e){await fetch(`/api/string?index=${i}&enabled=${e?1:0}`,{method:'POST'});refresh()}"
    "async function setColor(){let v=color.value;await fetch(`/api/onboard?red=${parseInt(v.slice(1,3),16)}&green=${parseInt(v.slice(3,5),16)}&blue=${parseInt(v.slice(5),16)}`,{method:'POST'});refresh()}refresh()</script>";

static esp_err_t serve_index(httpd_req_t *request)
{
    httpd_resp_set_type(request, "text/html");
    return httpd_resp_send(request, INDEX_HTML, HTTPD_RESP_USE_STRLEN);
}

static bool query_integer(httpd_req_t *request, const char *name, long *value)
{
    char query[128];
    char text_value[16];
    if (httpd_req_get_url_query_str(request, query, sizeof(query)) != ESP_OK ||
        httpd_query_key_value(query, name, text_value, sizeof(text_value)) != ESP_OK) {
        return false;
    }
    char *end;
    *value = strtol(text_value, &end, 10);
    return *text_value != '\0' && *end == '\0';
}

static esp_err_t send_bad_request(httpd_req_t *request, const char *message)
{
    return httpd_resp_send_err(request, HTTPD_400_BAD_REQUEST, message);
}

static esp_err_t set_external_string(httpd_req_t *request)
{
    long index;
    long enabled;
    if (!query_integer(request, "index", &index) || !query_integer(request, "enabled", &enabled) ||
        index < 0 || index >= EXTERNAL_LED_STRING_COUNT || (enabled != 0 && enabled != 1)) {
        return send_bad_request(request, "Expected index=0..3 and enabled=0|1");
    }
    ESP_RETURN_ON_ERROR(led_controller_set_external_enabled((size_t)index, enabled == 1), "web-server", "Could not update string");
    return httpd_resp_sendstr(request, "OK");
}

static esp_err_t set_onboard_led(httpd_req_t *request)
{
    long red;
    long green;
    long blue;
    if (!query_integer(request, "red", &red) || !query_integer(request, "green", &green) || !query_integer(request, "blue", &blue) ||
        red < 0 || red > 255 || green < 0 || green > 255 || blue < 0 || blue > 255) {
        return send_bad_request(request, "Expected red, green and blue values from 0 to 255");
    }
    ESP_RETURN_ON_ERROR(led_controller_set_onboard_color(red, green, blue), "web-server", "Could not update onboard LED");
    return httpd_resp_sendstr(request, "OK");
}

static esp_err_t serve_state(httpd_req_t *request)
{
    external_led_string_state_t strings[EXTERNAL_LED_STRING_COUNT];
    onboard_led_color_t onboard;
    led_controller_get_state(strings, &onboard);
    char response[512];
    int length = snprintf(response, sizeof(response),
        "{\"strings\":[{\"enabled\":%s,\"length\":%u,\"pattern\":\"%s\"},{\"enabled\":%s,\"length\":%u,\"pattern\":\"%s\"},{\"enabled\":%s,\"length\":%u,\"pattern\":\"%s\"},{\"enabled\":%s,\"length\":%u,\"pattern\":\"%s\"}],\"onboard\":{\"red\":%u,\"green\":%u,\"blue\":%u}}",
        strings[0].enabled ? "true" : "false", (unsigned)strings[0].led_count, strings[0].pattern_name,
        strings[1].enabled ? "true" : "false", (unsigned)strings[1].led_count, strings[1].pattern_name,
        strings[2].enabled ? "true" : "false", (unsigned)strings[2].led_count, strings[2].pattern_name,
        strings[3].enabled ? "true" : "false", (unsigned)strings[3].led_count, strings[3].pattern_name,
        onboard.red, onboard.green, onboard.blue);
    httpd_resp_set_type(request, "application/json");
    return httpd_resp_send(request, response, length);
}

esp_err_t web_server_start(void)
{
    httpd_config_t configuration = HTTPD_DEFAULT_CONFIG();
    configuration.core_id = 0;
    httpd_handle_t server = NULL;
    ESP_RETURN_ON_ERROR(httpd_start(&server, &configuration), "web-server", "Could not start HTTP server");
    const httpd_uri_t routes[] = {
        {.uri = "/", .method = HTTP_GET, .handler = serve_index},
        {.uri = "/api/state", .method = HTTP_GET, .handler = serve_state},
        {.uri = "/api/string", .method = HTTP_POST, .handler = set_external_string},
        {.uri = "/api/onboard", .method = HTTP_POST, .handler = set_onboard_led},
    };
    for (size_t route_index = 0; route_index < sizeof(routes) / sizeof(routes[0]); route_index++) {
        ESP_RETURN_ON_ERROR(httpd_register_uri_handler(server, &routes[route_index]), "web-server", "Could not register HTTP route");
    }
    return ESP_OK;
}
