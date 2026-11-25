#Requires -Version 5.1
Set-StrictMode -Version Latest

function Write-Utf8NoBomFile {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Content
    )

    $parentDir = Split-Path -Parent $Path
    if (-not [string]::IsNullOrWhiteSpace($parentDir) -and -not (Test-Path -LiteralPath $parentDir)) {
        if ($PSCmdlet.ShouldProcess($parentDir, 'Create parent directory')) {
            $null = New-Item -ItemType Directory -Path $parentDir -Force
        }
    }

    if ($PSCmdlet.ShouldProcess($Path, 'Write UTF-8 (no BOM) file')) {
        $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
        [System.IO.File]::WriteAllText($Path, $Content, $utf8NoBom)
    }
}

function Format-InvariantNumber {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [double]$Value,

        [Parameter(Mandatory = $false)]
        [int]$Decimals = 3
    )

    $rounded = [math]::Round($Value, $Decimals)
    $fmt = '0.' + ('0' * [math]::Max(1, $Decimals))
    if ($Decimals -le 0) {
        $fmt = '0'
    }
    return $rounded.ToString($fmt, [System.Globalization.CultureInfo]::InvariantCulture)
}

function Join-MultiPath {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Parts
    )

    if (@($Parts).Count -eq 0) {
        return ''
    }

    $current = $Parts[0]
    for ($i = 1; $i -lt @($Parts).Count; $i++) {
        if (-not [string]::IsNullOrWhiteSpace($Parts[$i])) {
            $current = Join-Path -Path $current -ChildPath $Parts[$i]
        }
    }
    return $current
}

function Resolve-CallerPath {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$BaseDirectory
    )

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return ''
    }

    if ([System.IO.Path]::IsPathRooted($Path)) {
        return [System.IO.Path]::GetFullPath($Path)
    }

    return [System.IO.Path]::GetFullPath((Join-Path -Path $BaseDirectory -ChildPath $Path))
}

function ConvertTo-WindowsArgString {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $false)]
        [string[]]$Arguments = @()
    )

    $escaped = New-Object System.Collections.Generic.List[string]
    foreach ($arg in $Arguments) {
        if ($null -eq $arg -or $arg.Length -eq 0) {
            $escaped.Add('""')
            continue
        }
        if ($arg -notmatch '[\s"]') {
            $escaped.Add($arg)
            continue
        }
        $inner = [regex]::Replace($arg, '(\\*)"', '$1$1\"')
        $inner = [regex]::Replace($inner, '(\\+)$', '$1$1')
        $escaped.Add('"' + $inner + '"')
    }
    return ($escaped -join ' ')
}

function Invoke-NativeProcess {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,

        [Parameter(Mandatory = $false)]
        [string[]]$Arguments = @()
    )

    $resolvedExe = $FilePath
    if (-not (Test-Path -LiteralPath $resolvedExe)) {
        $cmdInfo = Get-Command -Name $FilePath -ErrorAction SilentlyContinue
        if ($null -eq $cmdInfo) {
            throw ("Executable not found: {0}" -f $FilePath)
        }
        $resolvedExe = $cmdInfo.Source
    }

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $resolvedExe
    $psi.Arguments = ConvertTo-WindowsArgString -Arguments $Arguments
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true

    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi

    try {
        $null = $proc.Start()
        $stdoutTask = $proc.StandardOutput.ReadToEndAsync()
        $stderrTask = $proc.StandardError.ReadToEndAsync()
        $proc.WaitForExit()

        return [PSCustomObject]@{
            ExitCode = $proc.ExitCode
            StdOut   = $stdoutTask.GetAwaiter().GetResult()
            StdErr   = $stderrTask.GetAwaiter().GetResult()
        }
    }
    finally {
        if ($null -ne $proc) {
            $proc.Dispose()
        }
    }
}

function Get-AudioMediaInfo {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        throw ("Media file does not exist: {0}" -f $Path)
    }

    $res = Invoke-NativeProcess -FilePath 'ffprobe' -Arguments @(
        '-v', 'quiet',
        '-print_format', 'json',
        '-show_format',
        '-show_streams',
        $Path
    )

    if ($res.ExitCode -ne 0) {
        throw ("ffprobe failed for '{0}' (exit {1}): {2}" -f $Path, $res.ExitCode, $res.StdErr)
    }

    $probe = $res.StdOut | ConvertFrom-Json
    $streams = @()
    if ($null -ne $probe -and $null -ne $probe.streams) {
        $streams = @($probe.streams)
    }

    $audioStream = $streams | Where-Object { $_.codec_type -eq 'audio' } | Select-Object -First 1
    $videoStream = $streams | Where-Object { $_.codec_type -eq 'video' } | Select-Object -First 1

    $durationSec = 0.0
    if ($null -ne $probe.format -and $null -ne $probe.format.duration) {
        [double]$parsedDur = 0.0
        if ([double]::TryParse([string]$probe.format.duration, [System.Globalization.NumberStyles]::Float, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$parsedDur)) {
            $durationSec = [math]::Round($parsedDur, 4)
        }
    }
    elseif ($null -ne $audioStream -and $null -ne $audioStream.duration) {
        [double]$parsedAudioDur = 0.0
        if ([double]::TryParse([string]$audioStream.duration, [System.Globalization.NumberStyles]::Float, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$parsedAudioDur)) {
            $durationSec = [math]::Round($parsedAudioDur, 4)
        }
    }

    $sampleRate = 0
    $channels = 0
    $codecName = ''
    if ($null -ne $audioStream) {
        if ($null -ne $audioStream.sample_rate) {
            [int]::TryParse([string]$audioStream.sample_rate, [ref]$sampleRate) | Out-Null
        }
        if ($null -ne $audioStream.channels) {
            [int]::TryParse([string]$audioStream.channels, [ref]$channels) | Out-Null
        }
        $codecName = [string]$audioStream.codec_name
    }

    $bitRate = 0
    if ($null -ne $probe.format -and $null -ne $probe.format.bit_rate) {
        [int]::TryParse([string]$probe.format.bit_rate, [ref]$bitRate) | Out-Null
    }

    $item = Get-Item -LiteralPath $Path
    return [PSCustomObject]@{
        Path        = $item.FullName
        Bytes       = $item.Length
        DurationSec = $durationSec
        SampleRate  = $sampleRate
        Channels    = $channels
        Codec       = $codecName
        BitRate     = $bitRate
        HasAudio    = ($null -ne $audioStream)
        HasVideo    = ($null -ne $videoStream)
    }
}

function Measure-AudioIntegratedLoudness {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $false)]
        [double]$TargetLufs = -16.0
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        throw ("Audio file not found for loudness measurement: {0}" -f $Path)
    }

    $targetStr = Format-InvariantNumber -Value $TargetLufs -Decimals 1
    $afArg = "loudnorm=I={0}:TP=-1.5:LRA=11:print_format=json" -f $targetStr
    $res = Invoke-NativeProcess -FilePath 'ffmpeg' -Arguments @(
        '-hide_banner',
        '-nostats',
        '-i', $Path,
        '-af', $afArg,
        '-f', 'null',
        'NUL'
    )

    if ($res.ExitCode -ne 0) {
        throw ("FFmpeg loudnorm analysis failed for '{0}' (exit {1}): {2}" -f $Path, $res.ExitCode, $res.StdErr)
    }

    $match = [regex]::Match($res.StdErr, '(?s)\{\s*"input_i"\s*:.*?\}')
    if (-not $match.Success) {
        return [PSCustomObject]@{
            MeasuredI  = $null
            MeasuredTP = $null
            TargetLufs = $TargetLufs
            GainDb     = 0.0
            Valid      = $false
        }
    }

    $jsonObj = $match.Value | ConvertFrom-Json
    $rawI = [string]$jsonObj.input_i
    $rawTp = [string]$jsonObj.input_tp

    [double]$measuredI = 0.0
    [double]$measuredTp = 0.0
    $iOk = [double]::TryParse($rawI, [System.Globalization.NumberStyles]::Float, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$measuredI)
    $tpOk = [double]::TryParse($rawTp, [System.Globalization.NumberStyles]::Float, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$measuredTp)

    if (-not $iOk -or [double]::IsInfinity($measuredI) -or [double]::IsNaN($measuredI) -or $measuredI -lt -70.0) {
        return [PSCustomObject]@{
            MeasuredI  = $null
            MeasuredTP = if ($tpOk -and -not [double]::IsInfinity($measuredTp)) { $measuredTp } else { $null }
            TargetLufs = $TargetLufs
            GainDb     = 0.0
            Valid      = $false
        }
    }

    $gainDb = $TargetLufs - $measuredI
    if ($gainDb -gt 18.0) { $gainDb = 18.0 }
    if ($gainDb -lt -24.0) { $gainDb = -24.0 }
    $gainDb = [math]::Round($gainDb, 3)

    return [PSCustomObject]@{
        MeasuredI  = [math]::Round($measuredI, 3)
        MeasuredTP = if ($tpOk -and -not [double]::IsInfinity($measuredTp)) { [math]::Round($measuredTp, 3) } else { $null }
        TargetLufs = $TargetLufs
        GainDb     = $gainDb
        Valid      = $true
    }
}

function Convert-FlowAudioFile {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory = $true)]
        [string]$InputPath,

        [Parameter(Mandatory = $true)]
        [string]$OutputPath,

        [Parameter(Mandatory = $true)]
        [ValidateSet('wav', 'mp3', 'ogg')]
        [string]$Format,

        [Parameter(Mandatory = $false)]
        [int]$SampleRate = 48000,

        [Parameter(Mandatory = $false)]
        [double]$GainDb = 0.0,

        [Parameter(Mandatory = $false)]
        [string]$Bitrate = '320k',

        [Parameter(Mandatory = $false)]
        [double]$AlignDurationSec = 0.0
    )

    if (-not (Test-Path -LiteralPath $InputPath)) {
        throw ("Input audio file not found: {0}" -f $InputPath)
    }

    $outParent = Split-Path -Parent $OutputPath
    if (-not [string]::IsNullOrWhiteSpace($outParent) -and -not (Test-Path -LiteralPath $outParent)) {
        if ($PSCmdlet.ShouldProcess($outParent, 'Create destination directory')) {
            $null = New-Item -ItemType Directory -Path $outParent -Force
        }
    }

    $gainStr = Format-InvariantNumber -Value $GainDb -Decimals 3
    $afParts = New-Object System.Collections.Generic.List[string]
    $afParts.Add(("volume={0}dB" -f $gainStr))
    $afParts.Add('alimiter=limit=0.95')

    if ($AlignDurationSec -gt 0.0) {
        $durStr = Format-InvariantNumber -Value $AlignDurationSec -Decimals 6
        $afParts.Add('apad')
        $afParts.Add(("atrim=0:{0}" -f $durStr))
    }

    $afChain = ($afParts -join ',')

    $ffArgs = New-Object System.Collections.Generic.List[string]
    $ffArgs.Add('-y')
    $ffArgs.Add('-hide_banner')
    $ffArgs.Add('-loglevel')
    $ffArgs.Add('error')
    $ffArgs.Add('-i')
    $ffArgs.Add($InputPath)
    $ffArgs.Add('-vn')
    $ffArgs.Add('-sn')
    $ffArgs.Add('-dn')
    $ffArgs.Add('-ar')
    $ffArgs.Add([string]$SampleRate)
    $ffArgs.Add('-ac')
    $ffArgs.Add('2')
    $ffArgs.Add('-af')
    $ffArgs.Add($afChain)

    switch ($Format) {
        'wav' {
            $ffArgs.Add('-c:a')
            $ffArgs.Add('pcm_s16le')
        }
        'mp3' {
            $effectiveBitrate = if ([string]::IsNullOrWhiteSpace($Bitrate)) { '320k' } else { $Bitrate }
            $ffArgs.Add('-c:a')
            $ffArgs.Add('libmp3lame')
            $ffArgs.Add('-b:a')
            $ffArgs.Add($effectiveBitrate)
        }
        'ogg' {
            $ffArgs.Add('-c:a')
            $ffArgs.Add('libvorbis')
            $ffArgs.Add('-q:a')
            $ffArgs.Add('7')
        }
    }

    $ffArgs.Add($OutputPath)

    if ($PSCmdlet.ShouldProcess($OutputPath, ("Encode {0} from '{1}'" -f $Format.ToUpperInvariant(), $InputPath))) {
        $res = Invoke-NativeProcess -FilePath 'ffmpeg' -Arguments $ffArgs.ToArray()
        if ($res.ExitCode -ne 0) {
            throw ("FFmpeg encode failed for '{0}' -> '{1}' (exit {2}): {3}" -f $InputPath, $OutputPath, $res.ExitCode, $res.StdErr)
        }
        return (Get-Item -LiteralPath $OutputPath)
    }
    return $null
}

function Find-TrackAudioAssets {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$TrackDir,

        [Parameter(Mandatory = $false)]
        $TrackMeta = $null
    )

    $supportedExt = @('.wav', '.mp3', '.ogg', '.m4a', '.flac')
    $masterPath = $null

    if ($null -ne $TrackMeta -and $null -ne $TrackMeta.masterFile -and -not [string]::IsNullOrWhiteSpace([string]$TrackMeta.masterFile)) {
        $candidate = Resolve-CallerPath -Path ([string]$TrackMeta.masterFile) -BaseDirectory $TrackDir
        if (Test-Path -LiteralPath $candidate) {
            $masterPath = $candidate
        }
    }

    if ($null -eq $masterPath) {
        $masterFiles = @(Get-ChildItem -LiteralPath $TrackDir -File -ErrorAction SilentlyContinue |
            Where-Object { $_.BaseName -ieq 'master' -and ($supportedExt -contains $_.Extension.ToLowerInvariant()) } |
            Sort-Object Name)
        if (@($masterFiles).Count -gt 0) {
            $masterPath = $masterFiles[0].FullName
        }
    }

    if ($null -eq $masterPath) {
        $anyRootAudio = @(Get-ChildItem -LiteralPath $TrackDir -File -ErrorAction SilentlyContinue |
            Where-Object { $supportedExt -contains $_.Extension.ToLowerInvariant() } |
            Sort-Object Name)
        if (@($anyRootAudio).Count -gt 0) {
            $masterPath = $anyRootAudio[0].FullName
        }
    }

    $stemNames = @('drums', 'bass', 'instruments', 'vocals')
    $stemsMap = [ordered]@{}
    $stemsDir = Join-Path -Path $TrackDir -ChildPath 'stems'

    foreach ($stemName in $stemNames) {
        $foundStem = $null
        if ($null -ne $TrackMeta -and $null -ne $TrackMeta.stems) {
            $stemProp = $TrackMeta.stems.PSObject.Properties[$stemName]
            if ($null -ne $stemProp -and -not [string]::IsNullOrWhiteSpace([string]$stemProp.Value)) {
                $candidateStem = Resolve-CallerPath -Path ([string]$stemProp.Value) -BaseDirectory $TrackDir
                if (Test-Path -LiteralPath $candidateStem) {
                    $foundStem = $candidateStem
                }
            }
        }
        if ($null -eq $foundStem -and (Test-Path -LiteralPath $stemsDir)) {
            $stemFiles = @(Get-ChildItem -LiteralPath $stemsDir -File -ErrorAction SilentlyContinue |
                Where-Object { $_.BaseName -ieq $stemName -and ($supportedExt -contains $_.Extension.ToLowerInvariant()) } |
                Sort-Object Name)
            if (@($stemFiles).Count -gt 0) {
                $foundStem = $stemFiles[0].FullName
            }
        }
        if ($null -ne $foundStem) {
            $stemsMap[$stemName] = $foundStem
        }
    }

    return [PSCustomObject]@{
        MasterPath = $masterPath
        Stems      = $stemsMap
    }
}

function Test-AudioNeedsUpdate {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourcePath,

        [Parameter(Mandatory = $true)]
        [string]$DestinationPath,

        [Parameter(Mandatory = $false)]
        [switch]$Force
    )

    if ($Force) {
        return $true
    }
    if (-not (Test-Path -LiteralPath $DestinationPath)) {
        return $true
    }
    $srcItem = Get-Item -LiteralPath $SourcePath
    $dstItem = Get-Item -LiteralPath $DestinationPath
    return ($srcItem.LastWriteTimeUtc -gt $dstItem.LastWriteTimeUtc)
}

Export-ModuleMember -Function @(
    'Write-Utf8NoBomFile',
    'Format-InvariantNumber',
    'Join-MultiPath',
    'Resolve-CallerPath',
    'Invoke-NativeProcess',
    'Get-AudioMediaInfo',
    'Measure-AudioIntegratedLoudness',
    'Convert-FlowAudioFile',
    'Find-TrackAudioAssets',
    'Test-AudioNeedsUpdate'
)
