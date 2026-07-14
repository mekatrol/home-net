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
installed_count=0
updated_count=0
unchanged_count=0

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
        if cmp -s "$source" "$destination"; then
            printf 'Already current %s/%s\n' "$preset_type" "$preset_name"
            ((unchanged_count += 1))
            return
        fi

        mkdir -p "$backup_directory/$preset_type"
        cp -p "$destination" "$backup_directory/$preset_type/"
        cp -p "$source" "$destination"
        printf 'Updated %s/%s\n' "$preset_type" "$preset_name"
        ((updated_count += 1))
        return
    fi

    cp -p "$source" "$destination"
    printf 'Installed %s/%s\n' "$preset_type" "$preset_name"
    ((installed_count += 1))
}

install_preset printer 'Original Prusa MK4S MMU3 0.25 nozzle.ini'
install_preset physical_printer 'Prusa MK2.5S.ini'
install_preset physical_printer 'Prusa MK4S.ini'
install_preset filament 'PLA Low Temp.ini'

vendor_preset_file="$config_directory/vendor/PrusaResearch.ini"
if [[ ! -f "$vendor_preset_file" ]]; then
    printf 'Required bundled preset file is missing: %s\n' "$vendor_preset_file" >&2
    exit 1
fi

vendor_work_file="$(mktemp)"
cp -p "$vendor_preset_file" "$vendor_work_file"

disable_binary_gcode_for_vendor_preset() {
    local preset_name="$1"
    local next_work_file
    next_work_file="$(mktemp)"

    awk -v target="[printer:$preset_name]" '
        BEGIN { in_target = 0; found_target = 0; wrote_option = 0 }
        /^\[/ {
            if (in_target && !wrote_option) {
                print "binary_gcode = 0"
                wrote_option = 1
            }
            in_target = ($0 == target)
            if (in_target) found_target = 1
        }
        in_target && /^binary_gcode[[:space:]]*=/ {
            if (!wrote_option) print "binary_gcode = 0"
            wrote_option = 1
            next
        }
        { print }
        END {
            if (in_target && !wrote_option) print "binary_gcode = 0"
            if (!found_target) exit 3
        }
    ' "$vendor_work_file" > "$next_work_file" || {
        rm -f "$vendor_work_file" "$next_work_file"
        printf 'Bundled printer preset was not found: %s\n' "$preset_name" >&2
        exit 1
    }

    mv "$next_work_file" "$vendor_work_file"
}

disable_binary_gcode_for_vendor_preset 'Original Prusa i3 MK2.5S'
disable_binary_gcode_for_vendor_preset 'Original Prusa MK4S 0.25 nozzle'
disable_binary_gcode_for_vendor_preset 'Original Prusa MK4S 0.4 nozzle'
disable_binary_gcode_for_vendor_preset 'Original Prusa MK4S 0.6 nozzle'
disable_binary_gcode_for_vendor_preset 'Original Prusa MK4S MMU3 0.4 nozzle'
disable_binary_gcode_for_vendor_preset 'Original Prusa MK4S MMU3 0.6 nozzle'

if cmp -s "$vendor_work_file" "$vendor_preset_file"; then
    rm -f "$vendor_work_file"
    printf '%s\n' 'Bundled Prusa printer presets already have binary G-code disabled.'
    ((unchanged_count += 1))
else
    mkdir -p "$backup_directory/vendor"
    cp -p "$vendor_preset_file" "$backup_directory/vendor/"
    cp -p "$vendor_work_file" "$vendor_preset_file"
    rm -f "$vendor_work_file"
    printf '%s\n' 'Updated bundled Prusa printer presets to disable binary G-code.'
    ((updated_count += 1))
fi

# Remove superseded override files created by an earlier version of this bundle.
# Those files are identified by the alias metadata that the current clean-named
# presets no longer use.
for obsolete_preset in "$config_directory/printer/"*.ini; do
    [[ -f "$obsolete_preset" ]] || continue
    if grep -Fq 'alias = Original Prusa' "$obsolete_preset" && \
        grep -Fq 'binary_gcode = 0' "$obsolete_preset"; then
        mkdir -p "$backup_directory/printer"
        cp -p "$obsolete_preset" "$backup_directory/printer/"
        rm -f "$obsolete_preset"
        printf 'Removed superseded printer/%s\n' "$(basename "$obsolete_preset")"
        ((updated_count += 1))
    elif grep -Fq '# Match the bundled preset name while overriding its binary G-code capability.' "$obsolete_preset"; then
        mkdir -p "$backup_directory/printer"
        cp -p "$obsolete_preset" "$backup_directory/printer/"
        rm -f "$obsolete_preset"
        printf 'Removed ineffective duplicate printer/%s\n' "$(basename "$obsolete_preset")"
        ((updated_count += 1))
    fi
done

printf '\nPreset synchronization complete: %d installed, %d updated, %d already current.\n' \
    "$installed_count" "$updated_count" "$unchanged_count"
printf 'PrusaSlicer configuration directory:\n  %s\n' "$config_directory"
if ((updated_count > 0)); then
    printf 'Replaced files were backed up in:\n  %s\n' "$backup_directory"
fi
printf '%s\n' 'Start PrusaSlicer and verify the physical-printer selector.'
