[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string] $ConfigDirectory
)

$ErrorActionPreference = "Stop"

if (Get-Process -Name "prusa-slicer" -ErrorAction SilentlyContinue) {
    Write-Error "PrusaSlicer appears to be running. Close it before installing presets so it does not overwrite them."
    exit 1
}

if ([string]::IsNullOrWhiteSpace($ConfigDirectory)) {
    $ConfigDirectory = Join-Path $env:APPDATA "PrusaSlicer"
}

$ConfigDirectory = [Environment]::ExpandEnvironmentVariables($ConfigDirectory)
$ConfigFile = Join-Path $ConfigDirectory "PrusaSlicer.ini"

if (-not (Test-Path -LiteralPath $ConfigFile -PathType Leaf)) {
    Write-Error "No PrusaSlicer.ini found in '$ConfigDirectory'. Start PrusaSlicer, complete the Configuration Wizard, close it, and rerun this script. You may also pass the correct directory with -ConfigDirectory."
    exit 1
}

$MmuModelEnabled = Select-String -LiteralPath $ConfigFile -SimpleMatch "model:MK4SMMU3" -Quiet
if (-not $MmuModelEnabled) {
    Write-Error "The required MK4S MMU3 parent preset is not enabled. Enable MK4S MMU3 0.4 and 0.6 in the Configuration Wizard first."
    exit 1
}

$Timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$BackupDirectory = Join-Path $ConfigDirectory "preset-backup-before-install-$Timestamp"
$InstalledCount = 0
$UpdatedCount = 0
$UnchangedCount = 0

# Register the newly added vendor variant in the Configuration Wizard's enabled
# printer list; otherwise the physical-printer selector hides it.
$ConfigLines = [System.Collections.Generic.List[string]]::new()
foreach ($Line in [System.IO.File]::ReadAllLines($ConfigFile)) { $ConfigLines.Add($Line) }
$ConfigChanged = $false
$MmuVariantChanged = $false
$LinkPhysicalPrinter = $ConfigLines.Contains("printer = Original Prusa MK4S MMU3 0.25 nozzle")
$PhysicalPrinterLinked = $false
for ($Index = 0; $Index -lt $ConfigLines.Count; $Index++) {
    if ($ConfigLines[$Index] -match '^model:MK4SMMU3\s*=\s*(.*)$') {
        $Variants = @($Matches[1] -split ';' | ForEach-Object { $_.Trim() })
        if ($Variants -notcontains "0.25") {
            $ConfigLines[$Index] = "model:MK4SMMU3 = " + ((@("0.25") + $Variants) -join ";")
            $MmuVariantChanged = $true
            $ConfigChanged = $true
        }
    } elseif ($LinkPhysicalPrinter -and $ConfigLines[$Index] -eq "physical_printer = ") {
        $ConfigLines[$Index] = "physical_printer = Prusa MK4S * Original Prusa MK4S MMU3 0.25 nozzle"
        $PhysicalPrinterLinked = $true
        $ConfigChanged = $true
    }
}
if ($ConfigChanged) {
    New-Item -ItemType Directory -Path $BackupDirectory -Force | Out-Null
    Copy-Item -LiteralPath $ConfigFile -Destination $BackupDirectory -Force
    $Utf8WithoutBom = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllLines($ConfigFile, $ConfigLines, $Utf8WithoutBom)
    if ($MmuVariantChanged) { Write-Host "Enabled MK4S MMU3 0.25 in PrusaSlicer.ini" }
    if ($PhysicalPrinterLinked) { Write-Host "Linked MK4S MMU3 0.25 to physical printer Prusa MK4S" }
    $UpdatedCount++
} else {
    Write-Host "MK4S MMU3 0.25 selection is already current in PrusaSlicer.ini"
    $UnchangedCount++
}

function Install-Preset {
    param(
        [Parameter(Mandatory = $true)]
        [string] $PresetType,

        [Parameter(Mandatory = $true)]
        [string] $PresetName
    )

    $Source = Join-Path (Join-Path $PSScriptRoot $PresetType) $PresetName
    $DestinationDirectory = Join-Path $ConfigDirectory $PresetType
    $Destination = Join-Path $DestinationDirectory $PresetName

    if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) {
        throw "Backup bundle is incomplete; missing '$Source'."
    }

    New-Item -ItemType Directory -Path $DestinationDirectory -Force | Out-Null

    if (Test-Path -LiteralPath $Destination -PathType Leaf) {
        $SourceHash = (Get-FileHash -LiteralPath $Source -Algorithm SHA256).Hash
        $DestinationHash = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash
        if ($SourceHash -eq $DestinationHash) {
            Write-Host "Already current $PresetType/$PresetName"
            $script:UnchangedCount++
            return
        }

        $PresetBackupDirectory = Join-Path $BackupDirectory $PresetType
        New-Item -ItemType Directory -Path $PresetBackupDirectory -Force | Out-Null
        Copy-Item -LiteralPath $Destination -Destination $PresetBackupDirectory -Force
        Copy-Item -LiteralPath $Source -Destination $Destination -Force
        Write-Host "Updated $PresetType/$PresetName"
        $script:UpdatedCount++
        return
    }

    Copy-Item -LiteralPath $Source -Destination $Destination -Force
    Write-Host "Installed $PresetType/$PresetName"
    $script:InstalledCount++
}

Install-Preset -PresetType "physical_printer" -PresetName "Prusa MK2.5S.ini"
Install-Preset -PresetType "physical_printer" -PresetName "Prusa MK4S.ini"
Install-Preset -PresetType "filament" -PresetName "PLA Low Temp.ini"

# Prusa does not publish 0.25 mm MMU3 filament variants. Mirror every enabled
# standard MK4S filament into a small inheriting preset pinned to our printer.
# The marker makes generated files safe to recognize and update on later runs.
$FilamentSection = $false
foreach ($Line in [System.IO.File]::ReadAllLines($ConfigFile)) {
    if ($Line -eq "[filaments]") {
        $FilamentSection = $true
        continue
    }
    if ($FilamentSection -and $Line.StartsWith("[")) {
        break
    }
    if ($FilamentSection -and $Line -match '^(.+ @MK4S)\s*=\s*1\s*$') {
        $SourceFilament = $Matches[1].TrimEnd()
        $CopiedFilament = "$SourceFilament MMU3 0.25"
        $PresetName = "$CopiedFilament.ini"
        $DestinationDirectory = Join-Path $ConfigDirectory "filament"
        $Destination = Join-Path $DestinationDirectory $PresetName
        $Content = @(
            "# Generated by prusa-config-presets; source: MK4S 0.25 filament"
            "compatible_printers ="
            "compatible_printers_condition = printer_model==`"MK4SMMU3`" and nozzle_diameter[0]==0.25"
            "filament_settings_id = $CopiedFilament"
            "inherits = $SourceFilament"
        )
        $Desired = ($Content -join "`n") + "`n"

        New-Item -ItemType Directory -Path $DestinationDirectory -Force | Out-Null
        if (Test-Path -LiteralPath $Destination -PathType Leaf) {
            $Existing = [System.IO.File]::ReadAllText($Destination)
            if ($Existing.Replace("`r`n", "`n") -eq $Desired) {
                Write-Host "Already current filament/$PresetName"
                $script:UnchangedCount++
                continue
            }
            if (-not $Existing.StartsWith("# Generated by prusa-config-presets;")) {
                throw "Refusing to replace non-generated filament preset '$Destination'."
            }
            $PresetBackupDirectory = Join-Path $BackupDirectory "filament"
            New-Item -ItemType Directory -Path $PresetBackupDirectory -Force | Out-Null
            Copy-Item -LiteralPath $Destination -Destination $PresetBackupDirectory -Force
            $script:UpdatedCount++
            Write-Host "Updated filament/$PresetName"
        } else {
            $script:InstalledCount++
            Write-Host "Installed filament/$PresetName"
        }
        $Utf8WithoutBom = [System.Text.UTF8Encoding]::new($false)
        [System.IO.File]::WriteAllText($Destination, $Desired, $Utf8WithoutBom)
    }
}

$VendorPresetFile = Join-Path (Join-Path $ConfigDirectory "vendor") "PrusaResearch.ini"
if (-not (Test-Path -LiteralPath $VendorPresetFile -PathType Leaf)) {
    throw "Required bundled preset file is missing: '$VendorPresetFile'."
}

$VendorLines = [System.Collections.Generic.List[string]]::new()
foreach ($Line in [System.IO.File]::ReadAllLines($VendorPresetFile)) {
    $VendorLines.Add($Line)
}
$VendorChanged = $false

function Install-Mmu025VendorPrinter {
    $Header = "[printer:Original Prusa MK4S MMU3 0.25 nozzle]"
    if ($VendorLines.Contains($Header)) { return }
    foreach ($Line in @(
        "", "; Added by prusa-config-presets for the unsupported MMU3 0.25 combination.",
        $Header, "inherits = Original Prusa MK4S MMU3 0.4 nozzle", "printer_variant = 0.25",
        "nozzle_diameter = 0.25,0.25,0.25,0.25,0.25", "retract_length = 0.8,0.8,0.8,0.8,0.8",
        "retract_lift = 0.15,0.15,0.15,0.15,0.15", "max_layer_height = 0.15,0.15,0.15,0.15,0.15",
        "min_layer_height = 0.05,0.05,0.05,0.05,0.05", "default_print_profile = 0.15mm SPEED @MK4S 0.25",
        "default_filament_profile = `"Prusament PLA @MK4S`"", "binary_gcode = 0"
    )) { $VendorLines.Add($Line) }
    $script:VendorChanged = $true
}

function Enable-Mmu025PrinterVariant {
    $ModelHeader = $VendorLines.IndexOf("[printer_model:MK4SMMU3]")
    if ($ModelHeader -lt 0) { throw "Bundled MK4SMMU3 printer model was not found." }
    for ($Index = $ModelHeader + 1; $Index -lt $VendorLines.Count -and -not $VendorLines[$Index].StartsWith("["); $Index++) {
        if ($VendorLines[$Index] -match '^variants\s*=') {
            if ($VendorLines[$Index] -notmatch '0\.25') {
                $VendorLines[$Index] = $VendorLines[$Index] -replace '^variants\s*=\s*', 'variants = 0.25; '
                $script:VendorChanged = $true
            }
            return
        }
    }
    throw "Bundled MK4SMMU3 model has no variants declaration."
}

function Enable-Mmu025ForStandardMk4sProfiles {
    $SectionType = ""
    $OldCondition = "! single_extruder_multi_material"
    $NewCondition = "(! single_extruder_multi_material or (printer_model==`"MK4SMMU3`" and nozzle_diameter[0]==0.25))"

    for ($Index = 0; $Index -lt $VendorLines.Count; $Index++) {
        if ($VendorLines[$Index] -match '^\[(print|filament):') {
            $SectionType = $Matches[1]
        } elseif ($VendorLines[$Index].StartsWith("[")) {
            $SectionType = ""
        }

        if ($SectionType -and
            $VendorLines[$Index].StartsWith("compatible_printers_condition =") -and
            $VendorLines[$Index].Contains($OldCondition) -and
            -not $VendorLines[$Index].Contains($NewCondition)) {
            $VendorLines[$Index] = $VendorLines[$Index].Replace($OldCondition, $NewCondition)
            $script:VendorChanged = $true
        }
    }
}

function Disable-BinaryGcodeForVendorPreset {
    param(
        [Parameter(Mandatory = $true)]
        [string] $PresetName
    )

    $Target = "[printer:$PresetName]"
    $SectionStart = $VendorLines.IndexOf($Target)
    if ($SectionStart -lt 0) {
        throw "Bundled printer preset was not found: '$PresetName'."
    }

    $SectionEnd = $VendorLines.Count
    for ($Index = $SectionStart + 1; $Index -lt $VendorLines.Count; $Index++) {
        if ($VendorLines[$Index].StartsWith("[")) {
            $SectionEnd = $Index
            break
        }
    }

    for ($Index = $SectionStart + 1; $Index -lt $SectionEnd; $Index++) {
        if ($VendorLines[$Index] -match '^binary_gcode\s*=') {
            if ($VendorLines[$Index] -ne "binary_gcode = 0") {
                $VendorLines[$Index] = "binary_gcode = 0"
                $script:VendorChanged = $true
            }
            return
        }
    }

    $VendorLines.Insert($SectionEnd, "binary_gcode = 0")
    $script:VendorChanged = $true
}

Disable-BinaryGcodeForVendorPreset -PresetName "Original Prusa i3 MK2.5S"
Disable-BinaryGcodeForVendorPreset -PresetName "Original Prusa MK4S 0.25 nozzle"
Disable-BinaryGcodeForVendorPreset -PresetName "Original Prusa MK4S 0.4 nozzle"
Disable-BinaryGcodeForVendorPreset -PresetName "Original Prusa MK4S 0.6 nozzle"
Disable-BinaryGcodeForVendorPreset -PresetName "Original Prusa MK4S MMU3 0.4 nozzle"
Disable-BinaryGcodeForVendorPreset -PresetName "Original Prusa MK4S MMU3 0.6 nozzle"
Enable-Mmu025ForStandardMk4sProfiles
Enable-Mmu025PrinterVariant
Install-Mmu025VendorPrinter

if ($VendorChanged) {
    $VendorBackupDirectory = Join-Path $BackupDirectory "vendor"
    New-Item -ItemType Directory -Path $VendorBackupDirectory -Force | Out-Null
    Copy-Item -LiteralPath $VendorPresetFile -Destination $VendorBackupDirectory -Force
    $Utf8WithoutBom = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllLines($VendorPresetFile, $VendorLines, $Utf8WithoutBom)
    Write-Host "Updated bundled Prusa presets for binary G-code and MMU3 0.25 compatibility."
    $script:UpdatedCount++
} else {
    Write-Host "Bundled Prusa preset overrides are already current."
    $script:UnchangedCount++
}

$ShadowPrinter = Join-Path (Join-Path $ConfigDirectory "printer") "Original Prusa MK4S MMU3 0.25 nozzle.ini"
if (Test-Path -LiteralPath $ShadowPrinter -PathType Leaf) {
    $PresetBackupDirectory = Join-Path $BackupDirectory "printer"
    New-Item -ItemType Directory -Path $PresetBackupDirectory -Force | Out-Null
    Copy-Item -LiteralPath $ShadowPrinter -Destination $PresetBackupDirectory -Force
    Remove-Item -LiteralPath $ShadowPrinter -Force
    Write-Host "Removed shadowing user printer/Original Prusa MK4S MMU3 0.25 nozzle.ini"
    $script:UpdatedCount++
}

# Remove superseded override files created by an earlier version of this bundle.
# The current clean-named presets do not contain alias metadata.
$PrinterDirectory = Join-Path $ConfigDirectory "printer"
Get-ChildItem -LiteralPath $PrinterDirectory -Filter "*.ini" -File | ForEach-Object {
    $HasPrusaAlias = Select-String -LiteralPath $_.FullName -SimpleMatch "alias = Original Prusa" -Quiet
    $DisablesBinaryGcode = Select-String -LiteralPath $_.FullName -SimpleMatch "binary_gcode = 0" -Quiet
    if ($HasPrusaAlias -and $DisablesBinaryGcode) {
        $PresetBackupDirectory = Join-Path $BackupDirectory "printer"
        New-Item -ItemType Directory -Path $PresetBackupDirectory -Force | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $PresetBackupDirectory -Force
        Remove-Item -LiteralPath $_.FullName -Force
        Write-Host "Removed superseded printer/$($_.Name)"
        $script:UpdatedCount++
    } elseif (Select-String -LiteralPath $_.FullName -SimpleMatch "# Match the bundled preset name while overriding its binary G-code capability." -Quiet) {
        $PresetBackupDirectory = Join-Path $BackupDirectory "printer"
        New-Item -ItemType Directory -Path $PresetBackupDirectory -Force | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $PresetBackupDirectory -Force
        Remove-Item -LiteralPath $_.FullName -Force
        Write-Host "Removed ineffective duplicate printer/$($_.Name)"
        $script:UpdatedCount++
    }
}

Write-Host ""
Write-Host "Preset synchronization complete: $InstalledCount installed, $UpdatedCount updated, $UnchangedCount already current."
Write-Host "PrusaSlicer configuration directory:"
Write-Host "  $ConfigDirectory"
if ($UpdatedCount -gt 0) {
    Write-Host "Replaced files were backed up in:"
    Write-Host "  $BackupDirectory"
}
Write-Host "Start PrusaSlicer and verify the physical-printer selector."
