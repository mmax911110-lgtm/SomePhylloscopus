param([Parameter(Mandatory=$true)][string]$Options, [switch]$Cleanup)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$settings = @{}
foreach ($line in [IO.File]::ReadAllLines($Options)) {
    $pair = $line.Split([char[]]'=', [int]2, [StringSplitOptions]::None)
    if ($pair.Length -eq 2) { $settings[$pair[0]] = $pair[1] }
}
$work = [IO.Path]::GetFullPath($settings.WorkDir).TrimEnd('\')
$marker = Join-Path $work '.somephylloscopus-installer'
$owner = 'SomePhylloscopus-v0.1.0-installer-cache-v1'
$stage = Join-Path $work 'stage'
$manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'download-manifest.json') -Raw | ConvertFrom-Json
$urlBase = 'https://github.com/mmax911110-lgtm/SomePhylloscopus/releases/download/v0.1.0'
$cancel = Join-Path $work 'cancel.request'

function Check-Cancel {
    if (Test-Path -LiteralPath $cancel) { throw 'Cancelled. Download progress is saved for next time.' }
}
function Progress([int]$percent, [string]$text) {
    Write-Output ('SP_PROGRESS|' + $percent + '|' + $text)
    Check-Cancel
}
function Hash-Stream([IO.Stream]$stream, [long]$count) {
    $algorithm = [Security.Cryptography.SHA256]::Create()
    $buffer = New-Object byte[] (4MB)
    try {
        while ($count -gt 0) {
            Check-Cancel
            $n = $stream.Read($buffer, 0, [int][Math]::Min($count, $buffer.Length))
            if ($n -eq 0) { throw 'Incomplete file.' }
            [void]$algorithm.TransformBlock($buffer, 0, $n, $buffer, 0)
            $count -= $n
        }
        [void]$algorithm.TransformFinalBlock($buffer, 0, 0)
        return [BitConverter]::ToString($algorithm.Hash).Replace('-', '').ToLowerInvariant()
    } finally { $algorithm.Dispose() }
}
function Verify([string]$path, $info) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $false }
    if ((Get-Item -LiteralPath $path).Length -ne $info.bytes) { return $false }
    $s = [IO.File]::OpenRead($path)
    try { return (Hash-Stream $s $info.bytes) -eq $info.sha256 } finally { $s.Dispose() }
}
function Safe-RemoveStage {
    $resolved = [IO.Path]::GetFullPath($stage)
    if ($resolved -ne ($work + '\stage') -or [IO.File]::ReadAllText($marker) -ne $owner) { throw 'Unsafe staging directory.' }
    if (Test-Path -LiteralPath $resolved) {
        $links = @(Get-Item -LiteralPath $resolved; Get-ChildItem -LiteralPath $resolved -Recurse -Force) | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }
        if ($links) { throw 'Unexpected link in staging directory.' }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
function Download-Part($part, [string]$path, [long]$assembled) {
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        Check-Cancel
        if (Verify $path $part) { return }
        [long]$offset = 0
        if (Test-Path -LiteralPath $path) {
            $offset = (Get-Item -LiteralPath $path).Length
            if ($offset -ge $part.bytes) { Remove-Item -LiteralPath $path; $offset = 0 }
        }
        $response = $null; $inputStream = $null; $out = $null
        try {
            $request = [Net.HttpWebRequest]::Create($urlBase + '/' + $part.file)
            $request.UserAgent = 'SomePhylloscopus-Setup/0.1.0'
            $request.Timeout = 20000
            $request.ReadWriteTimeout = 20000
            if ($offset -gt 0) { $request.AddRange($offset) }
            $response = $request.GetResponse()
            if ($offset -gt 0 -and [int]$response.StatusCode -eq 200) { $offset = 0 }
            if ($offset -gt 0 -and $response.Headers['Content-Range'] -notlike "bytes $offset-*") { throw 'Server returned an invalid resume offset.' }
            $out = [IO.File]::Open($path, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::Write, [IO.FileShare]::None)
            $out.SetLength($offset); $out.Position = $offset
            $inputStream = $response.GetResponseStream()
            $buffer = New-Object byte[] (1MB)
            $last = [DateTime]::MinValue
            while (($n = $inputStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
                Check-Cancel
                if ($out.Position + $n -gt $part.bytes) { throw 'Unexpected download size.' }
                $out.Write($buffer, 0, $n)
                if (([DateTime]::UtcNow - $last).TotalSeconds -ge 1) {
                    Progress ([int](60 * ($assembled + $out.Position) / $manifest.bytes)) ('Downloading ' + $part.file)
                    $last = [DateTime]::UtcNow
                }
            }
        } catch {
            Write-Output ('SP_LOG|Download retry ' + $attempt + ': ' + $_.Exception.Message.Split("`n")[0])
        } finally {
            if ($out) { $out.Dispose() }; if ($inputStream) { $inputStream.Dispose() }; if ($response) { $response.Dispose() }
        }
        Check-Cancel
        if (Verify $path $part) { return }
        if ($attempt -lt 3) { Start-Sleep -Seconds 2 }
    }
    throw ('Could not download and verify ' + $part.file + '. Reopen Setup to resume.')
}

try {
    if (-not $work.EndsWith('.somephylloscopus-setup-v0.1.0')) { throw 'Unexpected cache location.' }
    if (Test-Path -LiteralPath $work) {
        if (-not (Test-Path -LiteralPath $marker) -or [IO.File]::ReadAllText($marker) -ne $owner) { throw 'Cache directory is not owned by this installer.' }
        if ((Get-Item -LiteralPath $work).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Cache directory cannot be a link.' }
    } else {
        [void][IO.Directory]::CreateDirectory($work)
        [IO.File]::WriteAllText($marker, $owner)
    }
    if ($Cleanup) {
        Safe-RemoveStage
        foreach ($name in @($manifest.file, $manifest.file + '.downloading', 'cancel.request', '.somephylloscopus-installer')) {
            $p = Join-Path $work $name
            if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Force }
        }
        foreach ($part in $manifest.parts) {
            $p = Join-Path $work ($part.file + '.downloading')
            if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Force }
        }
        # Remove only if empty; unknown user files are never recursively removed.
        if (@(Get-ChildItem -LiteralPath $work -Force).Count -eq 0) { [IO.Directory]::Delete($work) }
        Write-Output 'SP_CLEANUP|OK'; exit 0
    }
    if (Test-Path -LiteralPath $cancel) { Remove-Item -LiteralPath $cancel }
    $lock = [IO.File]::Open((Join-Path $work 'install.lock'), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    try {
        $zipPath = Join-Path $work $manifest.file
        if ($settings.SourceZip) {
            $zipPath = [IO.Path]::GetFullPath($settings.SourceZip)
            Progress 0 'Checking the selected ZIP...'
            if (-not (Verify $zipPath $manifest)) { throw 'Selected ZIP size/SHA-256 does not match v0.1.0. Select the complete ZIP, not a part.' }
        } elseif (-not (Verify $zipPath $manifest)) {
            $partial = $zipPath + '.downloading'
            $assembly = [IO.File]::Open($partial, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
            try {
                [long]$offset = 0
                foreach ($part in $manifest.parts) {
                    Check-Cancel
                    if ($assembly.Length -ge $offset + $part.bytes) {
                        $assembly.Position = $offset
                        Progress ([int](60 * $offset / $manifest.bytes)) ('Checking saved ' + $part.file)
                        if ((Hash-Stream $assembly $part.bytes) -eq $part.sha256) { $offset += $part.bytes; continue }
                    }
                    $assembly.SetLength($offset); $assembly.Position = $offset
                    $partPath = Join-Path $work ($part.file + '.downloading')
                    $manual = if ($settings.SourceParts) { Join-Path $settings.SourceParts $part.file } else { '' }
                    if ($manual -and (Verify $manual $part)) {
                        $source = $manual
                        Progress ([int](60 * $offset / $manifest.bytes)) ('Reusing ' + $part.file)
                    } else {
                        Download-Part $part $partPath $offset
                        $source = $partPath
                    }
                    $stream = [IO.File]::OpenRead($source)
                    try { $stream.CopyTo($assembly, 4MB) } finally { $stream.Dispose() }
                    $assembly.Flush($true); $offset += $part.bytes
                    if ($source -eq $partPath) { Remove-Item -LiteralPath $partPath }
                }
                $assembly.SetLength($manifest.bytes)
                $assembly.Position = 0
                Progress 60 'Checking complete ZIP SHA-256...'
                if ((Hash-Stream $assembly $manifest.bytes) -ne $manifest.sha256) { throw 'Complete ZIP SHA-256 mismatch.' }
            } finally { $assembly.Dispose() }
            if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath }
            [IO.File]::Move($partial, $zipPath)
        }
        Progress 62 'Preparing files...'
        Safe-RemoveStage
        [void][IO.Directory]::CreateDirectory($stage)
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $archive = [IO.Compression.ZipFile]::OpenRead($zipPath)
        try {
            $prefix = 'SomePhylloscopus-v0.1.0-Windows-NVIDIA/'
            $total = ($archive.Entries | Measure-Object -Property Length -Sum).Sum
            [long]$done = 0; $previousPercent = -1
            $buffer = New-Object byte[] (4MB)
            $seen = New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
            foreach ($entry in $archive.Entries) {
                Check-Cancel
                if (-not $entry.FullName.StartsWith($prefix)) { throw 'Unexpected archive root.' }
                $rel = $entry.FullName.Substring($prefix.Length)
                if (-not $rel -or $rel.Contains(':') -or $rel.Contains('\')) { throw 'Invalid archive path.' }
                $dest = [IO.Path]::GetFullPath((Join-Path $stage $rel))
                if (-not $dest.StartsWith($stage + '\', [StringComparison]::OrdinalIgnoreCase) -or -not $seen.Add($dest)) { throw 'Unsafe or repeated archive path.' }
                [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($dest))
                $inputStream = $entry.Open(); $out = [IO.File]::Open($dest, [IO.FileMode]::CreateNew)
                try {
                    while (($n = $inputStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
                        Check-Cancel; $out.Write($buffer, 0, $n); $done += $n
                        $percent = [int](62 + 38 * $done / $total)
                        if ($percent -ne $previousPercent) {
                            Progress $percent 'Unpacking application and model files...'
                            $previousPercent = $percent
                        }
                    }
                    if ($out.Length -ne $entry.Length) { throw 'Extracted file length mismatch.' }
                } finally { $inputStream.Dispose(); $out.Dispose() }
            }
        } finally { $archive.Dispose() }
        foreach ($required in @('柳莺识别.exe', 'NVIDIA/runtime/pythonw.exe', 'app/gui.py', 'assets/plates/index.json')) {
            if (-not (Test-Path -LiteralPath (Join-Path $stage $required))) { throw ('Missing application file: ' + $required) }
        }
        Progress 100 'Download and preparation complete.'
    } finally {
        $lock.Dispose()
        Remove-Item -LiteralPath (Join-Path $work 'install.lock') -ErrorAction SilentlyContinue
    }
    exit 0
} catch {
    Write-Output ('SP_ERROR|' + $_.Exception.Message)
    exit 1
}
