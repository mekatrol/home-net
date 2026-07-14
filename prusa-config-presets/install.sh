#!/usr/bin/env bash

set -euo pipefail

script_directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ $# -gt 1 ]]; then
    printf 'Usage: %s [PrusaSlicer-config-directory]\n' "$0" >&2
    exit 2
fi

if [[ $# -eq 1 ]]; then
    config_directory="${1/#\~/$HOME}"
elif [[ -d "$HOME/.var/app/com.prusa3d.PrusaSlicer/config/PrusaSlicer" ]]; then
    config_directory="$HOME/.var/app/com.prusa3d.PrusaSlicer/config/PrusaSlicer"
elif [[ -d "$HOME/.config/PrusaSlicer" ]]; then
    config_directory="$HOME/.config/PrusaSlicer"
else
    printf '%s\n' 'Could not find a PrusaSlicer configuration directory.' >&2
    printf '%s\n' 'Start PrusaSlicer once, close it, and rerun this script.' >&2
    printf 'Or specify the directory: %s /path/to/PrusaSlicer\n' "$0" >&2
    exit 1
fi

if pgrep -x prusa-slicer >/dev/null 2>&1 || pgrep -x PrusaSlicer >/dev/null 2>&1; then
    printf '%s\n' 'PrusaSlicer appears to be running.' >&2
    printf '%s\n' 'Close it before installing presets so it does not overwrite them.' >&2
    exit 1
fi

if [[ ! -f "$config_directory/PrusaSlicer.ini" ]]; then
    printf 'No PrusaSlicer.ini found in: %s\n' "$config_directory" >&2
    printf '%s\n' 'Run the Configuration Wizard once before installing this bundle.' >&2
    exit 1
fi

required_parent='Original Prusa MK4S MMU3 0.4 nozzle'
if ! grep -Fq 'model:MK4SMMU3' "$config_directory/PrusaSlicer.ini"; then
    printf 'Required bundled parent preset is not enabled: %s\n' "$required_parent" >&2
    printf '%s\n' 'Enable MK4S MMU3 0.4 and 0.6 in the Configuration Wizard first.' >&2
    exit 1
fi

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_directory="$config_directory/preset-backup-before-install-$timestamp"
mkdir -p "$backup_directory"

install_preset() {
    local preset_type="$1"
    local preset_name="$2"
    local source="$script_directory/$preset_type/$preset_name"
    local destination_directory="$config_directory/$preset_type"
    local destination="$destination_directory/$preset_name"

    if [[ ! -f "$source" ]]; then
        printf 'Backup bundle is incomplete; missing: %s\n' "$source" >&2
        exit 1
    fi

    mkdir -p "$destination_directory"
    if [[ -f "$destination" ]]; then
        mkdir -p "$backup_directory/$preset_type"
        cp -p "$destination" "$backup_directory/$preset_type/"
    fi
    cp -p "$source" "$destination"
    printf 'Installed %s/%s\n' "$preset_type" "$preset_name"
}

install_preset printer 'Original Prusa MK4S MMU3 0.25 nozzle.ini'
install_preset physical_printer 'Prusa MK2.5S.ini'
install_preset physical_printer 'Prusa MK4S.ini'
install_preset filament 'PLA Low Temp.ini'

printf '\nInstalled presets into:\n  %s\n' "$config_directory"
printf 'Replaced files, if any, were backed up in:\n  %s\n' "$backup_directory"
printf '%s\n' 'Start PrusaSlicer and verify the physical-printer selector.'
