#!/usr/bin/env python3
import usb.core
import usb.util
import time
import subprocess
import re

# ---------- CONFIG ----------
VENDOR_ID = 0x0001  # MEC0003 bridge
PRODUCT_ID = 0x0000
TIMEOUT = 5000  # ms for USB control transfer

POLL_INTERVAL = 2.0  # seconds between polls

# How long we tolerate being on battery before shutdown (seconds)
GRACE_ON_BATTERY = 300  # e.g. 5 minutes

# Set to True to actually call shutdown
ENABLE_SHUTDOWN = False
SHUTDOWN_CMD = ["sudo", "shutdown", "-h", "now", "UPS battery low"]
# ----------------------------

NUM_RE = re.compile(r"[^0-9.+-]")  # characters to strip from numeric tokens


def find_ups():
    """Find and claim the MEC0003 UPS device."""
    dev = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
    if dev is None:
        raise RuntimeError("MEC0003 UPS device not found (0001:0000).")

    # Detach any kernel driver if present (often not needed, but safe)
    try:
        if dev.is_kernel_driver_active(0):
            dev.detach_kernel_driver(0)
    except (NotImplementedError, usb.core.USBError):
        pass

    dev.set_configuration()
    usb.util.claim_interface(dev, 0)
    return dev


def megatec_q1_from_usb(dev):
    """
    Request Megatec/Q1 string via USB string descriptor (index 3, lang 0x0409).
    This matches behaviour seen with many MEC0003+UPSmart devices.
    """
    raw = dev.ctrl_transfer(
        0x80,  # bmRequestType: device-to-host, standard, device
        0x06,  # bRequest: GET_DESCRIPTOR
        0x0303,  # wValue: type=STRING(0x03), index=3
        0x0409,  # wIndex: language ID (en-US)
        102,  # wLength
        TIMEOUT,
    )

    if len(raw) < 4:
        raise RuntimeError(f"Response too short: {list(raw)}")

    # USB string descriptor: [bLength, bDescType, UTF-16LE...]
    data_utf16 = bytes(raw[2:])
    text = data_utf16.decode("utf-16le", errors="ignore").strip("\x00")

    # Strip parentheses and control chars
    cleaned = text.strip().strip("()").strip("\r\n")
    return cleaned


def clean_num(token: str) -> float:
    """Strip non-numeric noise and convert to float."""
    cleaned = NUM_RE.sub("", token)
    if cleaned == "" or cleaned == "." or cleaned == "+" or cleaned == "-":
        raise ValueError(f"Empty numeric after cleaning: {token!r}")
    return float(cleaned)


def parse_megatec_q1(line: str):
    """
    Parse a Megatec Q1 status line, tolerating stray control characters.

    Expected logical format:
      MMM.M NNN.N PPP.P QQQ RR.R SS.S TT.T b7b6b5b4b3b2b1b0
    """
    parts = line.split()
    if len(parts) < 8:
        raise ValueError(f"Not enough fields in Megatec line: {parts!r}")

    # Clean numeric tokens individually
    vin = clean_num(parts[0])
    vin_fault = clean_num(parts[1])
    vout = clean_num(parts[2])
    load_pct = int(clean_num(parts[3]))
    freq = clean_num(parts[4])
    batt_v = clean_num(parts[5])
    temp_c = clean_num(parts[6])

    flags = parts[7].strip()
    # Strip any non 0/1 from flags too
    flags = "".join(c for c in flags if c in "01")

    if len(flags) != 8:
        raise ValueError(
            f"Flags field should be 8 bits, got: {flags!r} from {parts[7]!r}"
        )

    b7, b6, b5, b4, b3, b2, b1, b0 = flags

    return {
        "input_voltage": vin,
        "input_fault_voltage": vin_fault,
        "output_voltage": vout,
        "load_percent": load_pct,
        "input_frequency": freq,
        "battery_voltage": batt_v,
        "temperature_c": temp_c,
        "flags_raw": flags,
        "on_battery": (b7 == "1"),
        "battery_low": (b6 == "1"),
        "avr_active": (b5 == "1"),
        "ups_failed": (b4 == "1"),
        "standby_type": (b3 == "1"),
        "test_in_progress": (b2 == "1"),
        "shutdown_active": (b1 == "1"),
        "beeper_on": (b0 == "1"),
    }


def maybe_shutdown():
    """Trigger system shutdown if enabled."""
    if not ENABLE_SHUTDOWN:
        print("[DRY RUN] Would shutdown now.")
        return

    print(">>> Executing shutdown:", " ".join(SHUTDOWN_CMD))
    try:
        subprocess.Popen(SHUTDOWN_CMD)
    except Exception as e:
        print("ERROR starting shutdown:", e)


def main():
    dev = find_ups()
    print("UPS found and interface claimed.")

    on_battery_since = None

    while True:
        try:
            line = megatec_q1_from_usb(dev)
            status = parse_megatec_q1(line)
        except Exception as e:
            print("ERROR querying UPS:", e)
            time.sleep(POLL_INTERVAL)
            continue

        on_batt = status["on_battery"]
        batt_low = status["battery_low"]

        vin = status["input_voltage"]
        vout = status["output_voltage"]
        batt_v = status["battery_voltage"]
        load = status["load_percent"]

        print(
            f"Vin={vin:.1f}V, Vout={vout:.1f}V, Load={load}%, "
            f"Batt={batt_v:.2f}V, on_battery={on_batt}, "
            f"battery_low={batt_low}, flags={status['flags_raw']}"
        )

        now = time.time()

        if on_batt:
            if on_battery_since is None:
                on_battery_since = now
                print(">>> Mains failed, UPS on battery.")

            elapsed = now - on_battery_since
            print(f"On battery for {elapsed:.0f} seconds.")

            # Immediate shutdown if battery_low
            if batt_low:
                print(">>> Battery low flag set – initiating shutdown.")
                maybe_shutdown()
                break

            # Grace-period shutdown
            if elapsed >= GRACE_ON_BATTERY:
                print(">>> On battery longer than grace period – initiating shutdown.")
                maybe_shutdown()
                break

        else:
            if on_battery_since is not None:
                print(">>> Mains restored, UPS back on line.")
                on_battery_since = None

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
