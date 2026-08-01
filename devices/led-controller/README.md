# LED Controller

ESP-IDF C project for the footprint-compatible Waveshare ESP32-S3-Zero and
ESP32-C6-Zero development boards. The firmware provides
a Wi-Fi controller for up to four independent external addressable LED strings.
The onboard addressable LED can also be controlled. Each external string's
solid colour, intensity, physical length, and control length are configured
directly through the controller's local web interface. No application server is
required.

Supported boards are:

- **Waveshare ESP32-S3-Zero (WS-25081):** ESP32-S3 target, 4 MB flash,
  2 MB quad SPI PSRAM, and onboard WS2812 data on GPIO 21.
- **Waveshare ESP32-C6-Zero (WS-27035):** ESP32-C6 target, 4 MB flash, no
  external PSRAM, and onboard WS2812 data on GPIO 8.

Both use the USB Serial/JTAG console. The external LED outputs use the same
physical carrier-board pads, which map to GPIO 4, 3, 5, and 6 on the S3 and
GPIO 3, 2, 4, and 5 on the C6.

## VS Code setup

1. Install the **Espressif IDF** VS Code extension.
2. Open `devices/led-controller` as the VS Code folder.
3. Run `ESP-IDF: Open ESP-IDF Installation Manager` and install ESP-IDF.
4. Run `ESP-IDF: Select Current ESP-IDF Version`.
5. Run `Terminal: Run Task`, choose **Set board**, and select the connected
   board. This also selects the correct ESP-IDF chip target.
6. Plug in the board.
7. Run `Terminal: Run Task`, then choose `Flash and Monitor`.

## Architecture

- Core 0 runs ESP-IDF's Wi-Fi driver and the controller's HTTP server.
- Remote Control Transceiver (RMT) hardware generates the four external LED
  waveforms. The outputs are updated serially so all four remain available on
  the ESP32-C6, which has fewer RMT transmit channels. Frames are applied
  immediately for a preview or at startup, then refreshed about every 500 ms
  so an LED string recovers automatically if its power is switched off and
  back on.

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

- controller board (constrained to the currently selected ESP-IDF target)
- Wi-Fi SSID and password
- GPIO for each external LED output (S3 defaults: GPIO 4, 3, 5, and 6; C6
  defaults: GPIO 3, 2, 4, and 5)

To change boards from a terminal, run one of:

```sh
scripts/esp-idf-task.sh . set-board esp32-s3-zero
scripts/esp-idf-task.sh . set-board esp32-c6-zero
```

Changing boards regenerates `sdkconfig`; the Set board task preserves the Wi-Fi
SSID and password across that operation. Target-specific checked-in defaults
enable PSRAM only for the ESP32-S3-Zero. The selection is remembered locally,
and each target uses its own build directory (`build-esp32s3` or
`build-esp32c6`) so a Flash task cannot reuse an image built for the other chip.

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

- `Set board`
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

The ESP32-S3-Zero uses GPIO 21 for its onboard WS2812; the ESP32-C6-Zero uses
GPIO 8. The visually similar ESP32-C3 version uses GPIO 10, while other ESP32-S3
mini boards may use GPIO 48, and those variants are not configured here. If the
firmware flashes and logs colours but the LED remains dark, verify the exact
board revision and inspect its LED solder bridge. Some revisions leave that
bridge open so the GPIO remains available on the edge connector; it must be
bridged for the onboard LED to receive the data signal.
