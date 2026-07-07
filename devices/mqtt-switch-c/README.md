# MQTT Switch C

ESP-IDF C port of `devices/mqtt-switch` for a Wemos ESP32-S2 Mini.

## VS Code setup

1. Install the **Espressif IDF** VS Code extension.
2. Open `devices/mqtt-switch-c` as the VS Code folder.
3. Run `ESP-IDF: Open ESP-IDF Installation Manager` and install an ESP-IDF version.
4. Run `ESP-IDF: Select Current ESP-IDF Version`.
5. Run `ESP-IDF: Set Espressif Device Target` and choose `esp32s2` if prompted.
6. Run `ESP-IDF: SDK Configuration editor` and set the values under `MQTT switch`.
7. Plug in the Wemos ESP32-S2 Mini.
8. Run `Terminal: Run Task`, then choose `Flash and Monitor`.

ESP-IDF v6 installs MQTT through the component manager. The dependency is
declared in `main/idf_component.yml` and will be downloaded during the first
build.

`sdkconfig` is intentionally ignored because it stores the Wi-Fi and MQTT values
you enter through menuconfig. `sdkconfig.defaults` stays checked in with safe
placeholder defaults.

The checked-in `.vscode/tasks.json` also exposes terminal tasks:

- `Set target`
- `Clean`
- `Build`
- `Flash`
- `Monitor`
- `Flash and Monitor`
- `Clean, Build, and Flash`

Those terminal tasks are portable and do not commit local ESP-IDF installation
paths. They run through `scripts/esp-idf-task.sh`, which uses `idf.py` if it is
already on `PATH`, or sources ESP-IDF from `ESP_IDF_EXPORT_SH`, `IDF_PATH`, or
common install locations under `$HOME`. `Flash` builds before flashing, so
`Clean, Build, and Flash` runs `Clean` and then `Flash`.

Use the checked-in `Flash` or `Flash and Monitor` task for normal flashing. The
ESP-IDF extension's built-in flash command may still print esptool deprecation
warnings because it invokes the older `esptool.py write_flash` wrapper.

## Flash troubleshooting

If flashing stops at `Connecting...`, the build has succeeded and the failure is
at the serial connection stage.

- Check that the board is visible: `ls -l /dev/ttyACM* /dev/ttyUSB*`
- If the serial port is missing, unplug/replug the board.
- If permissions are denied, add your user to the serial group, then log out and
  back in: `sudo usermod -aG dialout $USER`
- If the port exists but esptool still cannot connect, put the ESP32-S2 in
  bootloader mode: hold `BOOT`/`0`, tap `RESET`, release `BOOT`/`0`, then run
  the flash task again.

## Runtime behavior

- Connects to Wi-Fi.
- Connects to MQTT and subscribes to the configured set topic.
- Accepts JSON payloads such as `{"enabled": true, "on": true}`.
- Drives the configured output GPIO when both `enabled` and `on` are true.
- Publishes status JSON to the configured status topic.
- Shows recent MQTT traffic on the onboard status LED.
- Blinks the status LED after the MQTT inactivity warning window.
- Restarts the device after the MQTT inactivity timeout.
