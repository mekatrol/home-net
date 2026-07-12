#include "web_server.h"

#include <stdlib.h>
#include <string.h>

#include "esp_check.h"
#include "esp_http_server.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "led_controller.h"
#include "led_settings.h"

#define REBOOT_TASK_STACK_SIZE 2048
#define REBOOT_TASK_PRIORITY 5
#define REBOOT_RESPONSE_DELAY_MILLISECONDS 1000

static const char INDEX_HTML[] =
    "<!doctype html><meta name=viewport content='width=device-width'><title>LED controller</title>"
    "<style>body{font:18px sans-serif;max-width:42rem;margin:2rem auto;padding:0 1rem}button,input{font:inherit;margin:.3rem}input[type=number]{width:7rem}section{padding:1rem;border:1px solid #aaa;margin:1rem 0}.status{min-height:1.5em}</style>"
    "<h1>LED controller</h1><section id=strings></section>"
    "<section><h2>Settings</h2><h3>Onboard LED colour</h3><p><input id=color type=color value=#080808><button type=button onclick=setColor()>Preview colour</button></p><p>The selected colour is stored only when you press <strong>Save settings</strong>.</p><h3>External string lengths</h3><p>Set the number of LEDs physically connected to each output.</p><form id=settings></form><button type=button onclick=saveSettings()>Save settings</button><p id=settingsStatus class=status></p><button type=button onclick=rebootController()>Restart controller</button></section>"
    "<script>async function refresh(){let s=await(await fetch('/api/state')).json();strings.innerHTML=s.strings.map((x,i)=>`<p>String ${i+1}: ${x.length} LEDs, ${x.pattern} <button onclick=toggle(${i},${!x.enabled})>${x.enabled?'Turn off':'Turn on'}</button></p>`).join('');color.value='#'+[s.onboard.red,s.onboard.green,s.onboard.blue].map(x=>x.toString(16).padStart(2,'0')).join('')}"
    "async function toggle(i,e){await fetch(`/api/string?index=${i}&enabled=${e?1:0}`,{method:'POST'});refresh()}"
    "async function setColor(){let v=color.value;let r=await fetch(`/api/onboard?red=${parseInt(v.slice(1,3),16)}&green=${parseInt(v.slice(3,5),16)}&blue=${parseInt(v.slice(5),16)}`,{method:'POST'});settingsStatus.textContent=r.ok?'Colour preview applied. Use Save settings to keep it after a restart.':await r.text();if(r.ok)refresh()}"
    "function buildSettings(){settings.innerHTML=[0,1,2,3].map(i=>`<p><label>String ${i+1} <input id=count${i} type=number min=1 max=2048 required></label></p>`).join('')}"
    "async function loadSettings(){let s=await(await fetch('/api/settings')).json();s.ledCounts.forEach((n,i)=>document.getElementById('count'+i).value=n)}"
    "async function saveSettings(){if(!settings.reportValidity())return;let v=color.value,p=new URLSearchParams();[0,1,2,3].forEach(i=>p.set('count'+i,document.getElementById('count'+i).value));p.set('red',parseInt(v.slice(1,3),16));p.set('green',parseInt(v.slice(3,5),16));p.set('blue',parseInt(v.slice(5),16));settingsStatus.textContent='Saving settings...';let r=await fetch('/api/settings?'+p,{method:'POST'});settingsStatus.textContent=r.ok?'Settings saved. Restart the controller to apply LED count changes.':await r.text()}"
    "async function rebootController(){if(!confirm('Restart the LED controller now?'))return;settingsStatus.textContent='Restarting controller...';let r=await fetch('/api/reboot',{method:'POST'});if(!r.ok){settingsStatus.textContent=await r.text();return}settingsStatus.textContent='Restarting. This page will reconnect shortly.';setTimeout(()=>location.reload(),5000)}"
    "buildSettings();refresh();loadSettings()</script>";

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

static esp_err_t serve_settings(httpd_req_t *request)
{
    size_t led_counts[EXTERNAL_LED_STRING_COUNT];
    ESP_RETURN_ON_ERROR(led_settings_load_counts(led_counts), "web-server", "Could not load settings");
    char response[128];
    const int response_length = snprintf(
        response,
        sizeof(response),
        "{\"ledCounts\":[%u,%u,%u,%u]}",
        (unsigned)led_counts[0],
        (unsigned)led_counts[1],
        (unsigned)led_counts[2],
        (unsigned)led_counts[3]
    );
    httpd_resp_set_type(request, "application/json");
    return httpd_resp_send(request, response, response_length);
}

static esp_err_t save_settings(httpd_req_t *request)
{
    size_t led_counts[EXTERNAL_LED_STRING_COUNT];
    long parsed_led_counts[EXTERNAL_LED_STRING_COUNT];
    const char *const count_parameter_names[] = {"count0", "count1", "count2", "count3"};
    for (size_t string_index = 0; string_index < EXTERNAL_LED_STRING_COUNT; string_index++) {
        if (!query_integer(request, count_parameter_names[string_index], &parsed_led_counts[string_index]) ||
            parsed_led_counts[string_index] < MINIMUM_LEDS_PER_STRING ||
            parsed_led_counts[string_index] > MAXIMUM_LEDS_PER_STRING) {
            return send_bad_request(request, "Expected count0 through count3 values from 1 to 2048");
        }
        led_counts[string_index] = (size_t)parsed_led_counts[string_index];
    }

    long red;
    long green;
    long blue;
    if (!query_integer(request, "red", &red) || !query_integer(request, "green", &green) ||
        !query_integer(request, "blue", &blue) || red < 0 || red > 255 ||
        green < 0 || green > 255 || blue < 0 || blue > 255) {
        return send_bad_request(request, "Expected red, green and blue values from 0 to 255");
    }
    ESP_RETURN_ON_ERROR(
        led_settings_save(led_counts, (uint8_t)red, (uint8_t)green, (uint8_t)blue),
        "web-server",
        "Could not save LED settings"
    );
    return httpd_resp_sendstr(request, "OK");
}

static void reboot_after_http_response(void *task_parameter)
{
    (void)task_parameter;

    // Restarting immediately inside the HTTP handler can close the network
    // connection before the browser receives its success response. This short
    // delay lets the server finish transmitting the response first.
    vTaskDelay(pdMS_TO_TICKS(REBOOT_RESPONSE_DELAY_MILLISECONDS));
    esp_restart();
}

static esp_err_t reboot_controller(httpd_req_t *request)
{
    const BaseType_t task_created = xTaskCreate(
        reboot_after_http_response,
        "reboot-controller",
        REBOOT_TASK_STACK_SIZE,
        NULL,
        REBOOT_TASK_PRIORITY,
        NULL
    );
    if (task_created != pdPASS) {
        return httpd_resp_send_err(
            request,
            HTTPD_500_INTERNAL_SERVER_ERROR,
            "Could not schedule controller restart"
        );
    }

    return httpd_resp_sendstr(request, "Restarting");
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
        {.uri = "/api/settings", .method = HTTP_GET, .handler = serve_settings},
        {.uri = "/api/settings", .method = HTTP_POST, .handler = save_settings},
        {.uri = "/api/reboot", .method = HTTP_POST, .handler = reboot_controller},
    };
    for (size_t route_index = 0; route_index < sizeof(routes) / sizeof(routes[0]); route_index++) {
        ESP_RETURN_ON_ERROR(httpd_register_uri_handler(server, &routes[route_index]), "web-server", "Could not register HTTP route");
    }
    return ESP_OK;
}
