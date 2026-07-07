# home-net
A set of scripts, configuration, doco and docker setup for running a home network.

## structure

> scripts - various command utility shell scripts.  
> servers - directories containing pre-canned docker containers and other configuration and documentation for building home network servers and devices.

## VS Code tasks

When this repository root is open in VS Code, use `Terminal: Run Task` for
device firmware tasks. The MQTT switch C firmware tasks are plain shell tasks,
so they do not require the ESP-IDF task provider to be registered. The tasks run
through `scripts/esp-idf-task.sh`, which uses `idf.py` if it is already on
`PATH`, or sources ESP-IDF from `ESP_IDF_EXPORT_SH`, `IDF_PATH`, or common
install locations under `$HOME`.

- `MQTT Switch C: Build`
- `MQTT Switch C: Flash`
- `MQTT Switch C: Monitor`
- `MQTT Switch C: Flash and Monitor`
