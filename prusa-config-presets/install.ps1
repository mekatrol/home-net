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
New-Item -ItemType Directory -Path $BackupDirectory -Force | Out-Null

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
        $PresetBackupDirectory = Join-Path $BackupDirectory $PresetType
        New-Item -ItemType Directory -Path $PresetBackupDirectory -Force | Out-Null
        Copy-Item -LiteralPath $Destination -Destination $PresetBackupDirectory -Force
    }

    Copy-Item -LiteralPath $Source -Destination $Destination -Force
    Write-Host "Installed $PresetType/$PresetName"
}

Install-Preset -PresetType "printer" -PresetName "Original Prusa MK4S MMU3 0.25 nozzle.ini"
Install-Preset -PresetType "physical_printer" -PresetName "Prusa MK2.5S.ini"
Install-Preset -PresetType "physical_printer" -PresetName "Prusa MK4S.ini"
Install-Preset -PresetType "filament" -PresetName "PLA Low Temp.ini"

Write-Host ""
Write-Host "Installed presets into:"
Write-Host "  $ConfigDirectory"
Write-Host "Replaced files, if any, were backed up in:"
Write-Host "  $BackupDirectory"
Write-Host "Start PrusaSlicer and verify the physical-printer selector."
