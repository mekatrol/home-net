# LED Sequence Server

.NET 10 and Vue server for the ESP32 LED controllers. Human-readable color
definitions are converted to validated, base64-encoded wire frames when a
controller requests `GET /<controller-ip>`.

## Run with Docker

1. Change the example address in `data/controllers.json` to the controller's
   assigned IP address.
2. Point local DNS name `led-sequence.lan` at the Docker host.
3. Run `docker compose up --build -d`.
4. Check `http://led-sequence.lan/<controller-ip>`.

The container listens on host port 80 and mounts `./data` read-only. Editing
`controllers.json` takes effect on the next request; no restart is required.

## Definition format

Every output has an independent interval, physical byte order, LED count, and
up to 100 frames. A frame can fill the entire output:

```json
{ "fill": "#00b4ff" }
```

Or specify exactly one color per LED:

```json
{ "pixels": ["#ff0000", "#00ff00", "#0000ff"] }
```

RGBW outputs use eight hexadecimal digits: `#RRGGBBWW`. The server reorders
channels according to `format`, such as `grb` or `grbw`, before base64 encoding.

## Local development

Run the API:

```sh
dotnet run --project src/LedSequence.Api --urls http://localhost:5080
```

Run Vue in another terminal:

```sh
cd src/LedSequence.Web
npm install
npm run dev
```

Run API tests with `dotnet test` and build Vue with `npm run build`.
