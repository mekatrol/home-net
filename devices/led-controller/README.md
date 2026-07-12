# LED Controller

ESP-IDF C project for an ESP32-S3FH4R2 development board. The firmware provides
a Wi-Fi web interface for the onboard WS2812 addressable RGB LED and four
independent external addressable LED strings.

The supplied board is configured for:

- ESP32-S3 target
- 4 MB flash
- 2 MB quad SPI PSRAM
- onboard WS2812 data on GPIO 21
- USB Serial/JTAG console

## VS Code setup

1. Install the **Espressif IDF** VS Code extension.
2. Open `devices/led-controller` as the VS Code folder.
3. Run `ESP-IDF: Open ESP-IDF Installation Manager` and install ESP-IDF.
4. Run `ESP-IDF: Select Current ESP-IDF Version`.
5. Plug in the ESP32-S3 board.
6. Run `Terminal: Run Task`, then choose `Flash and Monitor`.

## Architecture

- Core 0 runs ESP-IDF's Wi-Fi driver and the HTTP server.
- Core 1 runs the LED pattern task.
- Four Remote Control Transceiver (RMT) transmit channels generate the four
  external LED waveforms in hardware after each frame is queued.
- The ESP32-S3 only has four RMT transmit channels. The onboard LED therefore
  uses the SPI peripheral, with each WS2812 bit encoded into three SPI bits.

RMT means that neither processor core has to bit-bang timing-sensitive LED
data. Each external string has its own frame buffer, length, channel, and
pattern state, so strings do not need to have matching lengths or effects.

## Configuration

Run `ESP-IDF: SDK Configuration editor (menuconfig)` and open **LED controller**
to set:

- Wi-Fi SSID and password
- GPIO for each external LED output (defaults: GPIO 4, 5, 6, and 7)
- LED count for each string (defaults: 30, 60, 90, and 120)

The firmware cannot connect until the Wi-Fi SSID is set. If it is left empty,
the serial monitor reports the missing setting and leaves the LED task running
instead of entering a reboot loop. An empty password is supported for an open
access point.

`sdkconfig` is ignored, so Wi-Fi credentials are not committed. Safe board
defaults remain checked in as `sdkconfig.defaults`. After flashing, the serial
log prints the assigned IP address. Open that address in a browser to toggle
the four strings and set the onboard LED colour.

The starter patterns are solid, chase, rainbow, and blink. They are deliberately
kept in the LED task rather than the HTTP handlers; web requests only update
shared state protected by a mutex. All external strings and the onboard LED
start turned off after every boot.

## SN74AHCT125N wiring

The four configured ESP32 GPIO outputs connect to the four `A` inputs. Tie each
corresponding active-low output-enable (`/OE`) input to ground, and connect each
`Y` output to one LED string data input. Power the SN74AHCT125N from 5 V and
connect the ESP32, buffer, LED power supply, and LED strings to a common ground.
A small series resistor (typically 220 to 470 ohms) near each buffer output is
recommended. Do not power LED strings from the ESP32 board; size the 5 V supply
for the string lengths and brightness limit.

The terminal tasks match the workflow used by `mqtt-switch-c`:

- `Set target`
- `Clean`
- `Build`
- `Flash`
- `Monitor`
- `Flash and Monitor`
- `Clean, Build, and Flash`

They call `scripts/esp-idf-task.sh`, which uses an active ESP-IDF environment or
finds an installation via `ESP_IDF_EXPORT_SH`, `IDF_PATH`, or common locations
under `$HOME`.

## Flash troubleshooting

If flashing stops at `Connecting...`, the build succeeded but the serial
connection did not:

- Check the port with `ls -l /dev/ttyACM* /dev/ttyUSB*`.
- Unplug and reconnect the board if the port is absent.
- On Linux, add your user to `dialout` if access is denied, then log out and in:
  `sudo usermod -aG dialout $USER`
- If the board still will not connect, hold `BOOT`, tap `RESET`, release `BOOT`,
  and run `Flash` again.

## Board pin note

The ESP32-S3 version of this board uses GPIO 21 for its onboard WS2812. The
visually similar ESP32-C3 version uses GPIO 10, while other ESP32-S3 mini boards
may use GPIO 48. If the firmware flashes and logs colors but the LED remains
dark, verify the exact board revision and inspect the LED solder bridge. Some
board revisions leave that bridge open so GPIO 21 remains available on the edge
connector; it must be bridged for the onboard LED to receive the data signal.
