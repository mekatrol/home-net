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

Install-Preset -PresetType "printer" -PresetName "Original Prusa MK4S MMU3 0.25 nozzle.ini"
Install-Preset -PresetType "physical_printer" -PresetName "Prusa MK2.5S.ini"
Install-Preset -PresetType "physical_printer" -PresetName "Prusa MK4S.ini"
Install-Preset -PresetType "filament" -PresetName "PLA Low Temp.ini"

$VendorPresetFile = Join-Path (Join-Path $ConfigDirectory "vendor") "PrusaResearch.ini"
if (-not (Test-Path -LiteralPath $VendorPresetFile -PathType Leaf)) {
    throw "Required bundled preset file is missing: '$VendorPresetFile'."
}

$VendorLines = [System.Collections.Generic.List[string]]::new()
foreach ($Line in [System.IO.File]::ReadAllLines($VendorPresetFile)) {
    $VendorLines.Add($Line)
}
$VendorChanged = $false

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

if ($VendorChanged) {
    $VendorBackupDirectory = Join-Path $BackupDirectory "vendor"
    New-Item -ItemType Directory -Path $VendorBackupDirectory -Force | Out-Null
    Copy-Item -LiteralPath $VendorPresetFile -Destination $VendorBackupDirectory -Force
    $Utf8WithoutBom = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllLines($VendorPresetFile, $VendorLines, $Utf8WithoutBom)
    Write-Host "Updated bundled Prusa printer presets to disable binary G-code."
    $script:UpdatedCount++
} else {
    Write-Host "Bundled Prusa printer presets already have binary G-code disabled."
    $script:UnchangedCount++
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
