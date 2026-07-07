#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 2 ]; then
  echo "usage: $0 <project-dir> <set-target|clean|build|flash|monitor|flash-monitor> [serial-port]" >&2
  exit 2
fi

project_dir=$1
action=$2
serial_port=${3:-/dev/ttyACM0}
idf_py=
idf_python=python3

prepend_path() {
  if [ -d "$1" ]; then
    PATH="$1:$PATH"
  fi
}

configure_versioned_esp_idf() {
  local idf_dir
  local version
  local version_dir
  local tools_path
  local python_bin
  local candidate

  for idf_dir in "$HOME"/.espressif/v*/esp-idf "$HOME"/esp/esp-idf; do
    if [ ! -f "$idf_dir/tools/idf.py" ]; then
      continue
    fi

    tools_path=${IDF_TOOLS_PATH:-"$HOME/.espressif/tools"}
    version_dir=$(basename "$(dirname "$idf_dir")")
    version=${version_dir#v}
    python_bin="$tools_path/python/$version_dir/venv/bin/python3"

    if [ ! -x "$python_bin" ]; then
      continue
    fi

    export IDF_PATH="$idf_dir"
    export IDF_TOOLS_PATH="$tools_path"
    export IDF_PYTHON_ENV_PATH="$tools_path/python/$version_dir/venv"
    export ESP_IDF_VERSION="$version"

    for candidate in \
      "$tools_path"/xtensa-esp-elf/*/xtensa-esp-elf/bin \
      "$tools_path"/riscv32-esp-elf/*/riscv32-esp-elf/bin \
      "$tools_path"/cmake/*/bin \
      "$tools_path"/ninja/* \
      "$tools_path"/esp-clang/*/esp-clang/bin
    do
      prepend_path "$candidate"
    done

    idf_py="$idf_dir/tools/idf.py"
    idf_python="$python_bin"
    export PATH
    return 0
  done

  return 1
}

source_esp_idf() {
  if [ -n "$idf_py" ] && [ -x "$idf_python" ]; then
    return
  fi

  if command -v idf.py >/dev/null 2>&1; then
    return
  fi

  if [ -n "${ESP_IDF_EXPORT_SH:-}" ] && [ -f "$ESP_IDF_EXPORT_SH" ]; then
    # shellcheck disable=SC1090
    if . "$ESP_IDF_EXPORT_SH" >/dev/null; then
      return
    fi
  fi

  if [ -n "${IDF_PATH:-}" ] && [ -f "$IDF_PATH/export.sh" ]; then
    # shellcheck disable=SC1091
    if . "$IDF_PATH/export.sh" >/dev/null; then
      return
    fi
  fi

  unset IDF_PATH
  unset IDF_PYTHON_ENV_PATH

  configure_versioned_esp_idf
}

run_idf() {
  source_esp_idf

  if command -v idf.py >/dev/null 2>&1; then
    idf.py -B build "$@"
    return
  fi

  if [ -n "$idf_py" ] && [ -x "$idf_python" ]; then
    "$idf_python" "$idf_py" -B build "$@"
    return
  fi

  if [ -z "$idf_py" ]; then
    echo "idf.py was not found." >&2
    echo "Set IDF_PATH, set ESP_IDF_EXPORT_SH, or run from an ESP-IDF terminal." >&2
    exit 127
  fi
}

diagnose_serial_port() {
  echo >&2
  echo "Flash failed while connecting to $serial_port." >&2

  if [ ! -e "$serial_port" ]; then
    echo "The serial port does not exist right now." >&2
    echo "Unplug/replug the board, then check the port with: ls -l /dev/ttyACM* /dev/ttyUSB*" >&2
    return
  fi

  ls -l "$serial_port" >&2 || true

  if [ ! -r "$serial_port" ] || [ ! -w "$serial_port" ]; then
    echo "The current user may not have read/write permission for this serial port." >&2
    echo "On Linux, add your user to the serial group, then log out and back in:" >&2
    echo "  sudo usermod -aG dialout \$USER" >&2
  fi

  if command -v lsof >/dev/null 2>&1; then
    lsof "$serial_port" >&2 || true
  fi

  echo "If the port exists and permissions are correct, put the ESP32-S2 in bootloader mode:" >&2
  echo "hold BOOT/0, tap RESET, release BOOT/0, then run the flash task again." >&2
}

cd "$project_dir"

case "$action" in
  set-target)
    run_idf set-target esp32s2
    ;;
  clean)
    run_idf fullclean
    ;;
  build)
    run_idf build
    ;;
  flash)
    run_idf build
    cd build
    source_esp_idf
    if ! "$idf_python" -m esptool \
      --chip esp32s2 \
      -b 460800 \
      --before default-reset \
      --after hard-reset \
      --port "$serial_port" \
      write-flash \
      --flash-mode dio \
      --flash-freq 80m \
      --flash-size 4MB \
      0x1000 bootloader/bootloader.bin \
      0x8000 partition_table/partition-table.bin \
      0x10000 mqtt_switch_c.bin
    then
      diagnose_serial_port
      exit 1
    fi
    ;;
  monitor)
    run_idf -p "$serial_port" monitor
    ;;
  flash-monitor)
    "$0" "$project_dir" flash "$serial_port"
    "$0" "$project_dir" monitor "$serial_port"
    ;;
  *)
    echo "unknown action: $action" >&2
    exit 2
    ;;
esac
