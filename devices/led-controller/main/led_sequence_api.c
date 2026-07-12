#include "led_sequence_api.h"

#include <ctype.h>
#include <stdlib.h>
#include <string.h>

#include "cJSON.h"
#include "esp_check.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "led_controller.h"
#include "mbedtls/base64.h"

#define SEQUENCE_API_HOST "led-sequence.lan"
#define FETCH_TASK_STACK_SIZE 8192
#define FETCH_TASK_PRIORITY 4
#define MAXIMUM_HTTP_RESPONSE_BYTES (1024 * 1024)
#define MAXIMUM_SEQUENCES_PER_STRING 100

static const char *TAG = "led-sequence-api";

typedef struct {
    char *bytes;
    size_t length;
    size_t capacity;
} response_buffer_t;

static esp_err_t receive_http_data(esp_http_client_event_t *event)
{
    if (event->event_id != HTTP_EVENT_ON_DATA || event->data_len == 0) {
        return ESP_OK;
    }
    response_buffer_t *response = event->user_data;
    const size_t required_capacity = response->length + event->data_len + 1;
    if (required_capacity > MAXIMUM_HTTP_RESPONSE_BYTES) {
        return ESP_ERR_INVALID_SIZE;
    }
    if (required_capacity > response->capacity) {
        size_t new_capacity = response->capacity == 0 ? 2048 : response->capacity;
        while (new_capacity < required_capacity) {
            new_capacity *= 2;
        }
        char *larger_buffer = realloc(response->bytes, new_capacity);
        ESP_RETURN_ON_FALSE(larger_buffer != NULL, ESP_ERR_NO_MEM, TAG, "Could not grow API response buffer");
        response->bytes = larger_buffer;
        response->capacity = new_capacity;
    }
    memcpy(response->bytes + response->length, event->data, event->data_len);
    response->length += event->data_len;
    response->bytes[response->length] = '\0';
    return ESP_OK;
}

static bool parse_format(const cJSON *string_object, char format[5], size_t *bytes_per_led)
{
    const cJSON *format_item = cJSON_GetObjectItemCaseSensitive(string_object, "format");
    if (!cJSON_IsString(format_item)) {
        return false;
    }
    const size_t length = strlen(format_item->valuestring);
    if (length != 3 && length != 4) {
        return false;
    }
    unsigned channel_mask = 0;
    for (size_t index = 0; index < length; index++) {
        const char channel = (char)tolower((unsigned char)format_item->valuestring[index]);
        if (channel != 'r' && channel != 'g' && channel != 'b' && channel != 'w') {
            return false;
        }
        const unsigned channel_bit = channel == 'r' ? 1U : channel == 'g' ? 2U : channel == 'b' ? 4U : 8U;
        if ((channel_mask & channel_bit) != 0) {
            return false;
        }
        channel_mask |= channel_bit;
        format[index] = channel;
    }
    if ((length == 3 && channel_mask != 7U) || (length == 4 && channel_mask != 15U)) {
        return false;
    }
    format[length] = '\0';
    *bytes_per_led = length;
    return true;
}

static bool read_positive_size(const cJSON *object, const char *property_name, size_t maximum, size_t *value)
{
    const cJSON *item = cJSON_GetObjectItemCaseSensitive(object, property_name);
    if (!cJSON_IsNumber(item) || item->valuedouble < 1 || item->valuedouble > maximum || item->valuedouble != item->valueint) {
        return false;
    }
    *value = (size_t)item->valueint;
    return true;
}

static esp_err_t decode_base64_exact(const cJSON *encoded_item, uint8_t *output, size_t expected_length)
{
    ESP_RETURN_ON_FALSE(cJSON_IsString(encoded_item), ESP_ERR_INVALID_ARG, TAG, "Base64 value must be a string");
    size_t decoded_length = 0;
    const int decode_result = mbedtls_base64_decode(
        output,
        expected_length,
        &decoded_length,
        (const unsigned char *)encoded_item->valuestring,
        strlen(encoded_item->valuestring)
    );
    ESP_RETURN_ON_FALSE(decode_result == 0 && decoded_length == expected_length, ESP_ERR_INVALID_SIZE, TAG, "Decoded frame has %u bytes; expected %u", (unsigned)decoded_length, (unsigned)expected_length);
    return ESP_OK;
}

static esp_err_t apply_string(const cJSON *root, size_t string_index)
{
    char property_name[16];
    snprintf(property_name, sizeof(property_name), "string%u", (unsigned)(string_index + 1));
    const cJSON *string_object = cJSON_GetObjectItemCaseSensitive(root, property_name);
    if (string_object == NULL) {
        // Missing outputs are deliberately untouched, as required by the API contract.
        return ESP_OK;
    }
    ESP_RETURN_ON_FALSE(cJSON_IsObject(string_object), ESP_ERR_INVALID_ARG, TAG, "%s must be an object", property_name);

    const cJSON *sequences = cJSON_GetObjectItemCaseSensitive(string_object, "sequences");
    ESP_RETURN_ON_FALSE(cJSON_IsArray(sequences), ESP_ERR_INVALID_ARG, TAG, "%s.sequences must be an array", property_name);
    const int sequence_count = cJSON_GetArraySize(sequences);
    if (sequence_count == 0) {
        return ESP_OK;
    }
    ESP_RETURN_ON_FALSE(sequence_count <= MAXIMUM_SEQUENCES_PER_STRING, ESP_ERR_INVALID_SIZE, TAG, "%s has more than 100 sequences", property_name);
    size_t interval_milliseconds;
    ESP_RETURN_ON_FALSE(read_positive_size(string_object, "sequenceIntervalMs", UINT32_MAX, &interval_milliseconds), ESP_ERR_INVALID_ARG, TAG, "%s.sequenceIntervalMs must be positive", property_name);

    char format[5];
    size_t bytes_per_led;
    ESP_RETURN_ON_FALSE(parse_format(string_object, format, &bytes_per_led), ESP_ERR_INVALID_ARG, TAG, "%s.format must contain RGB once each, with optional W", property_name);
    size_t declared_bytes_per_led;
    ESP_RETURN_ON_FALSE(read_positive_size(string_object, "bytesPerLed", 4, &declared_bytes_per_led) && declared_bytes_per_led == bytes_per_led, ESP_ERR_INVALID_ARG, TAG, "%s.bytesPerLed must match format", property_name);
    size_t led_count;
    ESP_RETURN_ON_FALSE(read_positive_size(string_object, "ledCount", 2048, &led_count), ESP_ERR_INVALID_ARG, TAG, "%s.ledCount must be from 1 to 2048", property_name);

    const size_t byte_count = (size_t)sequence_count * led_count * bytes_per_led;
    uint8_t *wire_bytes = malloc(byte_count);
    ESP_RETURN_ON_FALSE(wire_bytes != NULL, ESP_ERR_NO_MEM, TAG, "Could not allocate parsed data for %s", property_name);

    esp_err_t parse_result = ESP_OK;
    for (int sequence_index = 0; sequence_index < sequence_count && parse_result == ESP_OK; sequence_index++) {
        const size_t frame_byte_count = led_count * bytes_per_led;
        parse_result = decode_base64_exact(
            cJSON_GetArrayItem(sequences, sequence_index),
            wire_bytes + (size_t)sequence_index * frame_byte_count,
            frame_byte_count
        );
    }

    if (parse_result == ESP_OK) {
        const external_led_sequence_configuration_t configuration = {
            .led_count = led_count,
            .bytes_per_led = bytes_per_led,
            .sequence_count = (size_t)sequence_count,
            .sequence_bytes = wire_bytes,
        };
        parse_result = led_controller_apply_external_sequences(string_index, &configuration, (uint32_t)interval_milliseconds);
    } else {
        ESP_LOGE(TAG, "%s contains invalid base64 or a frame with the wrong byte length", property_name);
    }
    free(wire_bytes);
    return parse_result;
}

static esp_err_t apply_response(const char *json, size_t json_length)
{
    cJSON *root = cJSON_ParseWithLength(json, json_length);
    ESP_RETURN_ON_FALSE(root != NULL, ESP_ERR_INVALID_ARG, TAG, "Sequence API returned invalid JSON");

    esp_err_t result = ESP_OK;
    const cJSON *onboard = cJSON_GetObjectItemCaseSensitive(root, "onboard");
    if (cJSON_IsObject(onboard)) {
        char format[5];
        size_t bytes_per_led;
        size_t declared_bytes_per_led;
        size_t interval_milliseconds;
        const cJSON *sequences = cJSON_GetObjectItemCaseSensitive(onboard, "sequences");
        const int sequence_count = cJSON_IsArray(sequences) ? cJSON_GetArraySize(sequences) : -1;
        if (!parse_format(onboard, format, &bytes_per_led) || bytes_per_led != 3 ||
            !read_positive_size(onboard, "bytesPerLed", 4, &declared_bytes_per_led) || declared_bytes_per_led != bytes_per_led ||
            !read_positive_size(onboard, "sequenceIntervalMs", UINT32_MAX, &interval_milliseconds) ||
            sequence_count < 0 || sequence_count > MAXIMUM_SEQUENCES_PER_STRING) {
            result = ESP_ERR_INVALID_ARG;
        } else if (sequence_count == 0) {
            result = ESP_OK;
        } else {
            uint8_t *logical_colors = malloc((size_t)sequence_count * 3);
            if (logical_colors == NULL) {
                result = ESP_ERR_NO_MEM;
            }
            for (int sequence_index = 0; sequence_index < sequence_count && result == ESP_OK; sequence_index++) {
                uint8_t wire_color[3];
                result = decode_base64_exact(cJSON_GetArrayItem(sequences, sequence_index), wire_color, sizeof(wire_color));
                for (size_t channel_index = 0; channel_index < bytes_per_led && result == ESP_OK; channel_index++) {
                    const size_t logical_channel_index = format[channel_index] == 'r' ? 0 : format[channel_index] == 'g' ? 1 : 2;
                    logical_colors[(size_t)sequence_index * 3 + logical_channel_index] = wire_color[channel_index];
                }
            }
            if (result == ESP_OK) {
                const onboard_led_sequence_configuration_t configuration = {
                    .sequence_count = (size_t)sequence_count,
                    .red_green_blue_sequence_bytes = logical_colors,
                };
                result = led_controller_apply_onboard_sequences(&configuration, (uint32_t)interval_milliseconds);
            }
            free(logical_colors);
        }
    }
    for (size_t string_index = 0; string_index < EXTERNAL_LED_STRING_COUNT && result == ESP_OK; string_index++) {
        result = apply_string(root, string_index);
    }
    cJSON_Delete(root);
    return result;
}

static void fetch_task(void *task_parameter)
{
    char *controller_ip_address = task_parameter;
    char url[96];
    snprintf(url, sizeof(url), "http://%s/%s", SEQUENCE_API_HOST, controller_ip_address);
    free(controller_ip_address);

    response_buffer_t response = {0};
    const esp_http_client_config_t configuration = {
        .url = url,
        .event_handler = receive_http_data,
        .user_data = &response,
        .timeout_ms = 10000,
    };
    esp_http_client_handle_t client = esp_http_client_init(&configuration);
    esp_err_t result = client == NULL ? ESP_ERR_NO_MEM : esp_http_client_perform(client);
    if (result == ESP_OK && esp_http_client_get_status_code(client) != 200) {
        ESP_LOGE(TAG, "GET %s returned HTTP %d", url, esp_http_client_get_status_code(client));
        result = ESP_FAIL;
    }
    if (result == ESP_OK) {
        result = apply_response(response.bytes, response.length);
    }
    if (result == ESP_OK) {
        ESP_LOGI(TAG, "Applied LED sequences from %s", url);
    } else {
        ESP_LOGE(TAG, "Could not apply %s: %s", url, esp_err_to_name(result));
    }
    if (client != NULL) {
        esp_http_client_cleanup(client);
    }
    free(response.bytes);
    vTaskDelete(NULL);
}

esp_err_t led_sequence_api_fetch(const char *controller_ip_address)
{
    ESP_RETURN_ON_FALSE(controller_ip_address != NULL, ESP_ERR_INVALID_ARG, TAG, "Controller IP address is required");
    char *ip_copy = strdup(controller_ip_address);
    ESP_RETURN_ON_FALSE(ip_copy != NULL, ESP_ERR_NO_MEM, TAG, "Could not copy controller IP address");
    const BaseType_t created = xTaskCreate(fetch_task, "fetch-led-sequences", FETCH_TASK_STACK_SIZE, ip_copy, FETCH_TASK_PRIORITY, NULL);
    if (created != pdPASS) {
        free(ip_copy);
        return ESP_ERR_NO_MEM;
    }
    return ESP_OK;
}
