#Requires -Version 5.1
<#
.SYNOPSIS
    Opt-in helper to register the flow-music MCP server into Antigravity mcp_config.json.

.DESCRIPTION
    Creates a timestamped backup of mcp_config.json beside the original file, inserts or
    updates mcpServers["flow-music"] matching the local uv/FastMCP launcher convention,
    and saves the updated config as UTF-8 without BOM.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $false)]
    [string]$ConfigPath = '',

    [Parameter(Mandatory = $false)]
    [string]$ServerDir = 'G:\My Drive\Antigravity\Projects\MCP\flow-music-mcp'
)

$CallerDirectory = (Get-Location).Path
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $ScriptDir) { $ScriptDir = $PSScriptRoot }
Set-Location -Path $ScriptDir
$ErrorActionPreference = 'Stop'

Import-Module -Name (Join-Path -Path $ScriptDir -ChildPath 'FlowMusicCommon.psm1') -Force

$resolvedConfigPath = if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    Join-MultiPath -Parts @($env:USERPROFILE, '.gemini', 'config', 'mcp_config.json')
} else {
    Resolve-CallerPath -Path $ConfigPath -BaseDirectory $CallerDirectory
}

$resolvedServerDir = Resolve-CallerPath -Path $ServerDir -BaseDirectory $CallerDirectory
if (-not (Test-Path -LiteralPath $resolvedServerDir)) {
    throw ("flow-music-mcp server directory not found: {0}" -f $resolvedServerDir)
}

$backupPath = $null
if (Test-Path -LiteralPath $resolvedConfigPath) {
    $rawJson = Get-Content -LiteralPath $resolvedConfigPath -Raw -Encoding UTF8
    $configObj = if ([string]::IsNullOrWhiteSpace($rawJson)) {
        [PSCustomObject]@{}
    } else {
        $rawJson | ConvertFrom-Json
    }
    $stamp = (Get-Date).ToString('yyyyMMdd_HHmmss')
    $backupPath = "{0}.{1}.bak" -f $resolvedConfigPath, $stamp
} else {
    $configObj = [PSCustomObject]@{}
}

$serversProp = $configObj.PSObject.Properties['mcpServers']
if ($null -eq $serversProp -or $null -eq $serversProp.Value) {
    $configObj | Add-Member -MemberType NoteProperty -Name 'mcpServers' -Value ([PSCustomObject]@{}) -Force
}

$entryObj = [ordered]@{
    command = 'cmd.exe'
    args    = @(
        '/c',
        'uv',
        '--directory',
        $resolvedServerDir,
        'run',
        'python',
        '-m',
        'flow_music_mcp.server'
    )
}

if ($PSCmdlet.ShouldProcess($resolvedConfigPath, "Register 'flow-music' MCP server")) {
    if ($null -ne $backupPath -and (Test-Path -LiteralPath $resolvedConfigPath)) {
        Copy-Item -LiteralPath $resolvedConfigPath -Destination $backupPath -Force
    }

    $existingFlowProp = $configObj.mcpServers.PSObject.Properties['flow-music']
    if ($null -ne $existingFlowProp) {
        $existingFlowProp.Value = [PSCustomObject]$entryObj
    } else {
        $configObj.mcpServers | Add-Member -MemberType NoteProperty -Name 'flow-music' -Value ([PSCustomObject]$entryObj)
    }

    $updatedJson = $configObj | ConvertTo-Json -Depth 12
    Write-Utf8NoBomFile -Path $resolvedConfigPath -Content $updatedJson

    [PSCustomObject]@{
        Status     = 'Registered'
        ConfigPath = $resolvedConfigPath
        BackupPath = $backupPath
        ServerDir  = $resolvedServerDir
    }
}
