# PrusaSlicer printer preset backup

This bundle restores the following setup without replacing the rest of a fresh
PrusaSlicer configuration:

- Physical printer `Prusa MK2.5S`, using an inheriting 0.4 mm preset with binary G-code disabled.
- Physical printer `Prusa MK4S`, using the same PrusaLink connection for:
  - standard MK4S: 0.25, 0.4, and 0.6 mm;
  - MK4S with MMU3: 0.25, 0.4, and 0.6 mm.
- Inheriting printer presets that disable binary G-code for every listed printer/nozzle combination.
- Custom `PLA Low Temp` filament preset.
- Generated MMU3 0.25 mm copies of every enabled standard MK4S 0.25 mm filament preset.

The standard Prusa presets are supplied and updated by PrusaSlicer. The
installers set `binary_gcode = 0` directly in the relevant bundled preset
sections so their original names remain unchanged. The custom MMU3 0.25 mm
preset is added to the bundled vendor graph as an allowed `MK4SMMU3` variant and
inherits the MMU3 0.4 mm configuration with 0.25 mm overrides. Registering it in
the vendor graph lets PrusaSlicer resolve its print and filament presets.
The installers also add `0.25` to the enabled `MK4SMMU3` variants in
`PrusaSlicer.ini` so it appears in the physical-printer selector.
When that raw printer profile is active without a physical printer, the
installer relinks it to `Prusa MK4S` so the saved PrusaLink hostname and API key
apply to the MMU3 0.25 variant as well.

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

Because Prusa does not supply filament variants for the unsupported MMU3 0.25
mm combination, the installers create lightweight inheriting copies of the
enabled `@MK4S` filament presets and restrict those copies to the custom MMU3
0.25 mm printer using its model and nozzle compatibility condition. Generated
copies have an `MMU3 0.25` suffix and are updated only when their generated
content changes.

The bundled standard MK4S profile parents normally exclude multimaterial
printers. The installers extend those inherited compatibility conditions only
for the `MK4SMMU3` model with a 0.25 mm nozzle, allowing both the copied
filaments and the standard MK4S 0.25 mm print settings to be selected.

PrusaSlicer may replace its bundled preset file when its profiles are updated.
After a PrusaSlicer profile update, close PrusaSlicer and rerun the installer to
reapply the binary G-code overrides.

After installation, start PrusaSlicer and verify:

- `Prusa MK2.5S` has `Original Prusa i3 MK2.5S`;
- `Prusa MK4S` has all six standard/MMU3 nozzle choices.

## Query installed presets

PrusaSlicer's command-line interface can verify that it recognizes the custom
printer and can resolve its compatible print and filament profiles. Close the
GUI first so it does not rewrite configuration files during troubleshooting.

On Windows, use the console executable installed with PrusaSlicer:

```powershell
& "$env:ProgramFiles\Prusa3D\PrusaSlicer\prusa-slicer-console.exe" `
  --datadir "$env:APPDATA\PrusaSlicer" `
  --printer-profile "Original Prusa MK4S MMU3 0.25 nozzle" `
  --query-print-filament-profiles
```

On Linux with a native package, use `prusa-slicer`:

```bash
prusa-slicer \
  --datadir "$HOME/.config/PrusaSlicer" \
  --printer-profile 'Original Prusa MK4S MMU3 0.25 nozzle' \
  --query-print-filament-profiles
```

For the Flatpak package, run:

```bash
flatpak run com.prusa3d.PrusaSlicer \
  --datadir "$HOME/.var/app/com.prusa3d.PrusaSlicer/config/PrusaSlicer" \
  --printer-profile 'Original Prusa MK4S MMU3 0.25 nozzle' \
  --query-print-filament-profiles
```

Some native packages name the executable `PrusaSlicer`. For an AppImage,
replace `prusa-slicer` with the path to the executable AppImage. A successful
query returns JSON containing the requested `printer_profile` and a non-empty
`print_profiles` array; each print profile includes its compatible system and
user filament profiles.

To query all registered printer models and variants, replace the
`--printer-profile ... --query-print-filament-profiles` arguments with
`--query-printer-models` in any command above.

## Manual installation

The MMU3 0.25 integration requires the installer because it updates the bundled
vendor graph idempotently. Copying only the preset directories does not register
that unsupported printer variant with PrusaSlicer.

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
