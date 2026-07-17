# LED Controller

ESP-IDF C project for an ESP32-S3FH4R2 development board. The firmware provides
a Wi-Fi controller for up to four independent external addressable LED strings.
The onboard addressable LED can also be controlled. Each external string's
solid colour, intensity, physical length, and control length are configured
directly through the controller's local web interface. No application server is
required.

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

- Core 0 runs ESP-IDF's Wi-Fi driver and the controller's HTTP server.
- Four Remote Control Transceiver (RMT) transmit channels generate the four
  external LED waveforms in hardware. Frames are applied immediately for a
  preview or at startup, then refreshed about every 500 ms so an LED string
  recovers automatically if its power is switched off and back on.

RMT means that the processor does not have to bit-bang timing-sensitive LED
data. Each output has its own settings and frame, so strings do not need to have
matching lengths or colours. External WS2812 pixels use GRB (green, red, blue)
wire order.

## Web settings and preview

After DHCP assigns an address, open that address in a browser. Each of the four
strings has these settings:

- **Physical LED string length**: the number of pixels for which the controller
  sends data, from 0 to 2048.
- **LED control length**: the number of pixels at the start of the physical
  string that receive the selected colour. It cannot exceed physical length.
- **Colour**: the solid RGB colour for controlled pixels.
- **Intensity**: a 0 to 100 percent brightness scale applied to that colour.

The onboard LED has the same colour and intensity controls. Its physical and
control lengths are fixed at one, so those length fields are not shown for it.

Changing any field previews the complete string immediately but changes only
the controller's RAM. Pixels between control length and physical length are
explicitly sent black, which makes it possible to increase control length until
the end of an unknown string is found. Click **Save all settings** to commit the
current settings for all four outputs to NVS (non-volatile storage) flash. On a
restart, unsaved previews are discarded and the last saved settings are
restored.

## Configuration

Run `ESP-IDF: SDK Configuration editor (menuconfig)` and open **LED controller**
to set:

- Wi-Fi SSID and password
- GPIO for each external LED output (defaults: GPIO 4, 5, 6, and 7)

The firmware cannot expose its web interface until the Wi-Fi SSID is set. If it
is left empty, the serial monitor reports the missing setting without entering
a reboot loop. An empty password is supported for an open access point.

`sdkconfig` is ignored, so Wi-Fi credentials are not committed. Safe board
defaults remain checked in as `sdkconfig.defaults`. After flashing, the serial
log prints the assigned IP address. Open that address in a browser to preview
and save the four external string configurations or restart the controller.
Before settings are saved for the first time, all strings start off.

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
