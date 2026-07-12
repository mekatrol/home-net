#include "web_server.h"

#include <stdio.h>
#include <stdlib.h>

#include "esp_check.h"
#include "esp_http_server.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "led_controller.h"

#define REBOOT_TASK_STACK_SIZE 2048
#define REBOOT_TASK_PRIORITY 5
#define REBOOT_RESPONSE_DELAY_MILLISECONDS 1000

static const char INDEX_HTML[] =
    "<!doctype html><meta name=viewport content='width=device-width'><title>LED controller</title>"
    "<style>body{font:18px sans-serif;max-width:55rem;margin:2rem auto;padding:0 1rem}button,input{font:inherit;margin:.3rem}input[type=number]{width:6rem}section{padding:1rem;border:1px solid #aaa;margin:1rem 0}.row{display:grid;grid-template-columns:repeat(auto-fit,minmax(10rem,1fr));gap:.5rem}.row label{display:flex;flex-direction:column}.status{min-height:1.5em}.hint{color:#555;font-size:.9rem}</style>"
    "<h1>LED controller</h1><p>Changes preview immediately on the strings. They are written to flash only when you click <b>Save all settings</b>.</p><main id=strings></main>"
    "<p><button type=button onclick=save()>Save all settings</button> <button type=button onclick=rebootController()>Restart controller</button></p><p id=status class=status></p>"
    "<script>let timers={};function card(x,i){let c='#'+[x.red,x.green,x.blue].map(v=>v.toString(16).padStart(2,'0')).join('');return `<section><h2>String ${i+1}</h2><div class=row><label>Physical LED string length<input id=p${i} type=number min=0 max=2048 value=${x.physicalLength}></label><label>LED control length<input id=l${i} type=number min=0 max=2048 value=${x.controlLength}></label><label>Colour<input id=c${i} type=color value=${c}></label><label>Intensity: <span id=iv${i}>${x.intensity}%</span><input id=i${i} type=range min=0 max=100 value=${x.intensity}></label></div><p class=hint>LEDs from the control length to the physical length are sent black (off).</p></section>`}"
    "async function refresh(){let s=await(await fetch('/api/state')).json();strings.innerHTML=s.strings.map(card).join('');s.strings.forEach((_,i)=>{for(let id of ['p','l','c','i'])document.getElementById(id+i).addEventListener('input',()=>changed(i))})}"
    "function changed(n){iv(n).textContent=i(n).value+'%';clearTimeout(timers[n]);timers[n]=setTimeout(()=>preview(n),150)}function el(p,n){return document.getElementById(p+n)}function p(n){return el('p',n)}function l(n){return el('l',n)}function i(n){return el('i',n)}function c(n){return el('c',n)}function iv(n){return el('iv',n)}"
    "async function preview(n){let physical=Number(p(n).value),control=Number(l(n).value),v=c(n).value;if(control>physical){status.textContent='Control length cannot exceed physical length.';return false}let q=new URLSearchParams({index:n,physical,control,red:parseInt(v.slice(1,3),16),green:parseInt(v.slice(3,5),16),blue:parseInt(v.slice(5),16),intensity:i(n).value});let r=await fetch('/api/preview?'+q,{method:'POST'});status.textContent=r.ok?'Preview applied; not saved.':await r.text();return r.ok}"
    "async function save(){Object.values(timers).forEach(clearTimeout);for(let n=0;n<4;n++)if(!await preview(n))return;let r=await fetch('/api/save',{method:'POST'});status.textContent=r.ok?'All settings saved to flash.':await r.text()}"
    "async function rebootController(){if(!confirm('Restart the LED controller now? Unsaved previews will be discarded.'))return;status.textContent='Restarting controller...';let r=await fetch('/api/reboot',{method:'POST'});if(!r.ok){status.textContent=await r.text();return}setTimeout(()=>location.reload(),5000)}refresh()</script>";

static esp_err_t serve_index(httpd_req_t *request)
{
    httpd_resp_set_type(request, "text/html");
    return httpd_resp_send(request, INDEX_HTML, HTTPD_RESP_USE_STRLEN);
}

static bool query_integer(httpd_req_t *request, const char *name, long *value)
{
    char query[256];
    char text_value[16];
    if (httpd_req_get_url_query_str(request, query, sizeof(query)) != ESP_OK ||
        httpd_query_key_value(query, name, text_value, sizeof(text_value)) != ESP_OK) {
        return false;
    }
    char *end;
    *value = strtol(text_value, &end, 10);
    return *text_value != '\0' && *end == '\0';
}

static esp_err_t preview_string(httpd_req_t *request)
{
    long index, physical, control, red, green, blue, intensity;
    if (!query_integer(request, "index", &index) || !query_integer(request, "physical", &physical) ||
        !query_integer(request, "control", &control) || !query_integer(request, "red", &red) ||
        !query_integer(request, "green", &green) || !query_integer(request, "blue", &blue) ||
        !query_integer(request, "intensity", &intensity) || index < 0 || index >= EXTERNAL_LED_STRING_COUNT ||
        physical < 0 || physical > LED_STRING_MAXIMUM_PHYSICAL_LENGTH || control < 0 || control > physical ||
        red < 0 || red > 255 || green < 0 || green > 255 || blue < 0 || blue > 255 || intensity < 0 || intensity > 100) {
        return httpd_resp_send_err(request, HTTPD_400_BAD_REQUEST, "Invalid settings: control length must be no greater than physical length; maximum length is 2048");
    }
    const led_string_settings_t settings = {
        .physical_length = (size_t)physical, .control_length = (size_t)control,
        .red = (uint8_t)red, .green = (uint8_t)green, .blue = (uint8_t)blue,
        .intensity_percent = (uint8_t)intensity,
    };
    ESP_RETURN_ON_ERROR(led_controller_preview_string((size_t)index, &settings), "web-server", "Could not preview string");
    return httpd_resp_sendstr(request, "OK");
}

static esp_err_t save_settings(httpd_req_t *request)
{
    ESP_RETURN_ON_ERROR(led_controller_save_settings(), "web-server", "Could not save settings");
    return httpd_resp_sendstr(request, "OK");
}

static esp_err_t serve_state(httpd_req_t *request)
{
    led_string_settings_t strings[EXTERNAL_LED_STRING_COUNT];
    led_controller_get_settings(strings);
    char response[768];
    size_t used = 0;
    used += snprintf(response + used, sizeof(response) - used, "{\"strings\":[");
    for (size_t index = 0; index < EXTERNAL_LED_STRING_COUNT; index++) {
        used += snprintf(response + used, sizeof(response) - used,
            "%s{\"physicalLength\":%u,\"controlLength\":%u,\"red\":%u,\"green\":%u,\"blue\":%u,\"intensity\":%u}",
            index == 0 ? "" : ",", (unsigned)strings[index].physical_length, (unsigned)strings[index].control_length,
            strings[index].red, strings[index].green, strings[index].blue, strings[index].intensity_percent);
    }
    used += snprintf(response + used, sizeof(response) - used, "]}");
    httpd_resp_set_type(request, "application/json");
    return httpd_resp_send(request, response, used);
}

static void reboot_after_http_response(void *task_parameter)
{
    (void)task_parameter;
    vTaskDelay(pdMS_TO_TICKS(REBOOT_RESPONSE_DELAY_MILLISECONDS));
    esp_restart();
}

static esp_err_t reboot_controller(httpd_req_t *request)
{
    if (xTaskCreate(reboot_after_http_response, "reboot-controller", REBOOT_TASK_STACK_SIZE, NULL, REBOOT_TASK_PRIORITY, NULL) != pdPASS) {
        return httpd_resp_send_err(request, HTTPD_500_INTERNAL_SERVER_ERROR, "Could not schedule controller restart");
    }
    return httpd_resp_sendstr(request, "Restarting");
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
        {.uri = "/api/preview", .method = HTTP_POST, .handler = preview_string},
        {.uri = "/api/save", .method = HTTP_POST, .handler = save_settings},
        {.uri = "/api/reboot", .method = HTTP_POST, .handler = reboot_controller},
    };
    for (size_t index = 0; index < sizeof(routes) / sizeof(routes[0]); index++) {
        ESP_RETURN_ON_ERROR(httpd_register_uri_handler(server, &routes[index]), "web-server", "Could not register HTTP route");
    }
    return ESP_OK;
}
