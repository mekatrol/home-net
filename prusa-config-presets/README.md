# PrusaSlicer printer preset backup

This bundle restores the following setup without replacing the rest of a fresh
PrusaSlicer configuration:

- Physical printer `Prusa MK2.5S`, using an inheriting 0.4 mm preset with binary G-code disabled.
- Physical printer `Prusa MK4S`, using the same PrusaLink connection for:
  - standard MK4S: 0.25, 0.4, and 0.6 mm;
  - MK4S with MMU3: 0.25, 0.4, and 0.6 mm.
- Inheriting printer presets that disable binary G-code for every listed printer/nozzle combination.
- Custom `PLA Low Temp` filament preset.

The standard Prusa presets are supplied and updated by PrusaSlicer. The
installers set `binary_gcode = 0` directly in the relevant bundled preset
sections so their original names remain unchanged. The custom MMU3 0.25 mm
preset is a standalone resolved copy of the bundled MMU3 0.4 mm configuration
with the nozzle-specific values changed to 0.25 mm. Keeping it standalone avoids
PrusaSlicer falling back to generic firmware defaults when loading a custom
preset whose parent is bundled.

## Prepare the fresh installation

1. Install and start PrusaSlicer once.
2. In the Configuration Wizard, enable:
   - Original Prusa i3 MK2.5S: 0.4 mm;
   - Original Prusa MK4S: 0.25, 0.4, and 0.6 mm;
   - Original Prusa MK4S MMU3: 0.4 and 0.6 mm.
3. Finish the wizard and completely close PrusaSlicer.

## Install on Linux with Bash

Open a terminal in this backup directory and run:

```bash
./install.sh
```

The Bash script detects the Flatpak or usual native Linux configuration
directory. If the directory is somewhere else, pass it explicitly:

```bash
./install.sh /path/to/PrusaSlicer
```

## Install on Windows with PowerShell

Open PowerShell in this backup directory and run:

```powershell
.\install.ps1
```

The script uses `%APPDATA%\PrusaSlicer` by default. If PowerShell blocks local
scripts, run this command instead; it changes policy only for this process:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

To install into a different configuration directory:

```powershell
.\install.ps1 -ConfigDirectory "D:\path\to\PrusaSlicer"
```

Both installers check that PrusaSlicer is closed, verify that the required MMU3
parent preset is enabled, and synchronize every preset in this bundle. They are
safe to run again whenever this backup changes: missing files are installed,
changed files are backed up and replaced, and files already at the current
version are left untouched. Repeated runs therefore produce the same installed
configuration without accumulating backups for unchanged files.

PrusaSlicer may replace its bundled preset file when its profiles are updated.
After a PrusaSlicer profile update, close PrusaSlicer and rerun the installer to
reapply the binary G-code overrides.

After installation, start PrusaSlicer and verify:

- `Prusa MK2.5S` has `Original Prusa i3 MK2.5S`;
- `Prusa MK4S` has all six standard/MMU3 nozzle choices.

## Manual installation

While PrusaSlicer is closed, copy the contents of `printer/`,
`physical_printer/`, and `filament/` into the matching directories below the
active PrusaSlicer configuration directory.

Common locations:

- Windows: `%APPDATA%\PrusaSlicer`
- Linux Flatpak: `~/.var/app/com.prusa3d.PrusaSlicer/config/PrusaSlicer`
- Native Linux/AppImage: `~/.config/PrusaSlicer`

If a profile is missing or incompatible, rerun the Configuration Wizard and
confirm that all bundled profiles listed above are enabled.

## Security note

The files in `physical_printer/` contain the current PrusaLink hostnames and API
keys. Keep this backup private. Before sharing or committing it, remove the
`printhost_apikey` values and rotate the keys on the printers.

## Contents

```text
install.sh
install.ps1
README.md
printer/*.ini
physical_printer/Prusa MK2.5S.ini
physical_printer/Prusa MK4S.ini
filament/PLA Low Temp.ini
```
