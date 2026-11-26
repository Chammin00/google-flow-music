#Requires -Version 5.1
<#
.SYNOPSIS
    Starts the Google Flow Music Audition & Catalog Console (exports/hits/).

.DESCRIPTION
    Ensures dashboard/hits_catalog.json exists, locates or starts Serve-FlowMusicDashboard.py on
    127.0.0.1:$Port (default 8787, auto-stepping if an unrelated listener occupies the port),
    verifies readiness via /api/catalog, and opens http://127.0.0.1:$Port/ unless -NoBrowser is set.

.EXAMPLE
    Set-Location "G:\My Drive\Antigravity\Projects\Google Flow-music"
    .\scripts\Start-FlowMusicDashboard.ps1
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $false)]
    [int]$Port = 8787,

    [Parameter(Mandatory = $false)]
    [switch]$RebuildCatalog,

    [Parameter(Mandatory = $false)]
    [switch]$NoBrowser
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $ScriptDir) { $ScriptDir = $PSScriptRoot }
Set-Location -Path $ScriptDir
$ErrorActionPreference = 'Stop'

$HubRoot = Split-Path -Parent $ScriptDir
$BuildScript = Join-Path -Path $ScriptDir -ChildPath 'Build-HitsDashboardCatalog.py'
$ServerScript = Join-Path -Path $ScriptDir -ChildPath 'Serve-FlowMusicDashboard.py'
$CatalogPath = Join-Path -Path (Join-Path -Path $HubRoot -ChildPath 'dashboard') -ChildPath 'hits_catalog.json'

if ($RebuildCatalog -or -not (Test-Path -LiteralPath $CatalogPath)) {
    if ($PSCmdlet.ShouldProcess($CatalogPath, 'Build hits_catalog.json')) {
        & python $BuildScript | Out-Null
    }
}

$chosenPort = $Port
$dashboardOnline = $false

for ($candidate = $Port; $candidate -lt ($Port + 16); $candidate++) {
    $inUse = $false
    try {
        $conns = Get-NetTCPConnection -LocalPort $candidate -State Listen -ErrorAction SilentlyContinue
        if (@($conns).Count -gt 0) {
            $inUse = $true
        }
    } catch {}

    if ($inUse) {
        try {
            $catCheck = Invoke-RestMethod -Method Get -Uri ("http://127.0.0.1:{0}/api/catalog" -f $candidate) -TimeoutSec 1 -ErrorAction Stop
            if ($null -ne $catCheck -and $catCheck.schema -eq 'flow-music-hits-dashboard/1.0') {
                $chosenPort = $candidate
                $dashboardOnline = $true
                break
            }
        } catch {}
        continue
    }

    $chosenPort = $candidate
    break
}

if (-not $dashboardOnline) {
    if ($PSCmdlet.ShouldProcess(("127.0.0.1:{0}" -f $chosenPort), 'Start Flow Music Dashboard Server')) {
        $pyExe = 'python'
        $pyw = Get-Command -Name 'pythonw' -ErrorAction SilentlyContinue
        if ($null -ne $pyw -and $pyw.Source) {
            $pyExe = $pyw.Source
        }

        $argList = @(
            "`"$ServerScript`"",
            '--port', "$chosenPort",
            '--no-browser'
        )
        Start-Process -FilePath $pyExe -ArgumentList $argList -WorkingDirectory $HubRoot -WindowStyle Hidden | Out-Null

        $deadline = (Get-Date).AddSeconds(6)
        while ((Get-Date) -lt $deadline) {
            Start-Sleep -Milliseconds 200
            try {
                $catRes = Invoke-RestMethod -Method Get -Uri ("http://127.0.0.1:{0}/api/catalog" -f $chosenPort) -TimeoutSec 1 -ErrorAction Stop
                if ($null -ne $catRes -and $catRes.schema -eq 'flow-music-hits-dashboard/1.0') {
                    $dashboardOnline = $true
                    break
                }
            } catch {}
        }
    }
}

$url = ("http://127.0.0.1:{0}/" -f $chosenPort)
if (-not $NoBrowser -and $PSCmdlet.ShouldProcess($url, 'Open Flow Music Dashboard in browser')) {
    Start-Process $url
}

[PSCustomObject]@{
    Status      = if ($dashboardOnline) { 'Listening' } else { 'Starting' }
    Url         = $url
    Port        = $chosenPort
    CatalogPath = $CatalogPath
}
