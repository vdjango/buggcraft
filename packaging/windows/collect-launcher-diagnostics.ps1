param(
    [string]$LauncherPath = (Join-Path (Get-Location) 'Buggcraft-Setup.exe'),
    [string]$OutputDirectory = (Join-Path (Get-Location) ('Buggcraft-diagnostics-' + (Get-Date -Format 'yyyyMMdd-HHmmss')))
)

$ErrorActionPreference = 'Continue'
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null

function Write-Text([string]$Name, [string]$Value) {
    Set-Content -LiteralPath (Join-Path $OutputDirectory $Name) -Value $Value -Encoding UTF8
}

$resolved = $null
if (Test-Path -LiteralPath $LauncherPath) {
    $resolved = (Resolve-Path -LiteralPath $LauncherPath).Path
    $item = Get-Item -LiteralPath $resolved
    $hash = Get-FileHash -LiteralPath $resolved -Algorithm SHA256
    Write-Text 'launcher-file.txt' ("Path: {0}`r`nSize: {1}`r`nLastWriteTime: {2}`r`nSHA256: {3}`r`n" -f $resolved, $item.Length, $item.LastWriteTime.ToString('o'), $hash.Hash)
    Get-AuthenticodeSignature -LiteralPath $resolved | Format-List * | Out-File -LiteralPath (Join-Path $OutputDirectory 'launcher-signature.txt') -Encoding UTF8
} else {
    Write-Text 'launcher-file.txt' ("File not found: $LauncherPath")
}

# Copy only launcher logs, never account settings or downloaded runtime data.
$logRoot = if ($resolved) { Split-Path -Parent $resolved } else { (Get-Location).Path }
$appLogs = Join-Path $OutputDirectory 'launcher-logs'
New-Item -ItemType Directory -Force -Path $appLogs | Out-Null
Get-ChildItem -LiteralPath $logRoot -File | Where-Object {
    $_.Name -eq 'Buggcraft-install.log' -or $_.Name -like 'buggcraft*.log*'
} | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $appLogs $_.Name)
}
$failureRoot = Join-Path $logRoot 'error'
if (Test-Path -LiteralPath $failureRoot) {
    Get-ChildItem -LiteralPath $failureRoot -Directory | ForEach-Object {
        $archive = Join-Path $appLogs ('error-' + $_.Name)
        New-Item -ItemType Directory -Force -Path $archive | Out-Null
        Get-ChildItem -LiteralPath $_.FullName -File | Where-Object {
            $_.Name -eq 'Buggcraft-install.log' -or $_.Name -like 'buggcraft*.log*'
        } | ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $archive $_.Name)
        }
    }
}
$runtime = Join-Path $logRoot 'Buggcraft-runtime'
if (Test-Path -LiteralPath $runtime) {
    Get-ChildItem -LiteralPath $runtime -Recurse -File | Where-Object {
        $_.Name -in @('Buggcraft.exe', 'qwindows.dll', 'Qt6Core.dll', 'python311.dll')
    } | Select-Object FullName, Length, LastWriteTime | Format-List * |
        Out-File -LiteralPath (Join-Path $OutputDirectory 'runtime-files.txt') -Encoding UTF8
}

Get-ComputerInfo | Select-Object WindowsProductName, WindowsVersion, OsBuildNumber, OsArchitecture, CsManufacturer, CsModel, CsTotalPhysicalMemory, CsProcessors, BiosFirmwareType | Format-List * | Out-File (Join-Path $OutputDirectory 'system.txt') -Encoding UTF8
Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, BuildNumber, OSArchitecture, LastBootUpTime | Format-List * | Out-File (Join-Path $OutputDirectory 'operating-system.txt') -Encoding UTF8

$logs = @(
    'Microsoft-Windows-SmartScreen/Debug',
    'Microsoft-Windows-CodeIntegrity/Operational',
    'Microsoft-Windows-Windows Defender/Operational',
    'Application'
)
foreach ($log in $logs) {
    $safe = ($log -replace '[^A-Za-z0-9]+', '-')
    try {
        Get-WinEvent -FilterHashtable @{ LogName = $log; StartTime = (Get-Date).AddDays(-2) } -MaxEvents 200 -ErrorAction Stop |
            Select-Object TimeCreated, Id, LevelDisplayName, ProviderName, Message |
            Format-List * | Out-File (Join-Path $OutputDirectory ($safe + '.txt')) -Encoding UTF8
    } catch {
        Write-Text ($safe + '.txt') ("Could not read event log: $($_.Exception.Message)")
    }
}

Write-Text 'collection.txt' ("Collected: $(Get-Date -Format o)`r`nComputer: $env:COMPUTERNAME`r`nUser: $env:USERNAME`r`nLauncher: $LauncherPath`r`nOutput: $OutputDirectory")
$zip = $OutputDirectory + '.zip'
Compress-Archive -Path (Join-Path $OutputDirectory '*') -DestinationPath $zip -Force
Write-Host "Diagnostics saved to: $zip"
