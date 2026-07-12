#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 2 ]; then
  echo "usage: $0 <project-dir> <set-target|clean|build|flash|monitor|flash-monitor> [serial-port]" >&2
  exit 2
fi

project_dir=$1
action=$2
serial_port=${3:-/dev/ttyACM0}
idf_python=
idf_py=

prepend_path() {
  if [ -d "$1" ]; then
    PATH="$1:$PATH"
  fi
}

configure_versioned_esp_idf() {
  local idf_directory
  local version_directory
  local tools_path
  local candidate

  for idf_directory in "$HOME"/.espressif/v*/esp-idf "$HOME"/esp/esp-idf; do
    if [ ! -f "$idf_directory/tools/idf.py" ]; then
      continue
    fi

    tools_path=${IDF_TOOLS_PATH:-"$HOME/.espressif/tools"}
    version_directory=$(basename "$(dirname "$idf_directory")")
    idf_python="$tools_path/python/$version_directory/venv/bin/python3"

    if [ ! -x "$idf_python" ]; then
      continue
    fi

    export IDF_PATH="$idf_directory"
    export IDF_TOOLS_PATH="$tools_path"
    export IDF_PYTHON_ENV_PATH="$tools_path/python/$version_directory/venv"
    export ESP_IDF_VERSION="${version_directory#v}"

    for candidate in \
      "$tools_path"/xtensa-esp-elf/*/xtensa-esp-elf/bin \
      "$tools_path"/riscv32-esp-elf/*/riscv32-esp-elf/bin \
      "$tools_path"/cmake/*/bin \
      "$tools_path"/ninja/* \
      "$tools_path"/esp-clang/*/esp-clang/bin
    do
      prepend_path "$candidate"
    done

    idf_py="$idf_directory/tools/idf.py"
    export PATH
    return 0
  done

  return 1
}

find_esp_idf() {
  if command -v idf.py >/dev/null 2>&1; then
    return
  fi

  # Prefer the versioned installation layout used by ESP-IDF v6. This avoids
  # export.sh selecting an older, missing Python environment on machines that
  # have had more than one ESP-IDF release installed.
  if configure_versioned_esp_idf; then
    return
  fi

  if [ -n "${ESP_IDF_EXPORT_SH:-}" ] && [ -f "$ESP_IDF_EXPORT_SH" ]; then
    # shellcheck disable=SC1090
    . "$ESP_IDF_EXPORT_SH" >/dev/null
    return
  fi

  if [ -n "${IDF_PATH:-}" ] && [ -f "$IDF_PATH/export.sh" ]; then
    # shellcheck disable=SC1091
    . "$IDF_PATH/export.sh" >/dev/null
    return
  fi

  local export_script
  for export_script in "$HOME"/.espressif/v*/esp-idf/export.sh "$HOME"/esp/esp-idf/export.sh; do
    if [ -f "$export_script" ]; then
      # shellcheck disable=SC1090
      . "$export_script" >/dev/null
      return
    fi
  done

  echo "idf.py was not found." >&2
  echo "Set IDF_PATH, set ESP_IDF_EXPORT_SH, or run from an ESP-IDF terminal." >&2
  exit 127
}

run_idf() {
  find_esp_idf
  if command -v idf.py >/dev/null 2>&1; then
    idf.py -B build "$@"
  else
    "$idf_python" "$idf_py" -B build "$@"
  fi
}

cd "$project_dir"

case "$action" in
  set-target)
    run_idf set-target esp32s3
    ;;
  clean)
    run_idf fullclean
    ;;
  build)
    run_idf build
    ;;
  flash)
    run_idf -p "$serial_port" flash
    ;;
  monitor)
    run_idf -p "$serial_port" monitor
    ;;
  flash-monitor)
    run_idf -p "$serial_port" flash monitor
    ;;
  *)
    echo "unknown action: $action" >&2
    exit 2
    ;;
esac
