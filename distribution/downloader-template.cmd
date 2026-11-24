@echo off
setlocal
set "SOMEPHYLLOSCOPUS_DOWNLOADER=%~f0"
powershell.exe -NoLogo -NoProfile -Command "$ErrorActionPreference='Stop'; $raw=[IO.File]::ReadAllText($env:SOMEPHYLLOSCOPUS_DOWNLOADER); $source=[regex]::Split($raw,'\r?\n:PowerShellSource\r?\n',2)[1]; try { & ([ScriptBlock]::Create($source)) } catch { [Console]::Error.WriteLine($_.Exception.Message); [Console]::Error.WriteLine('Download stopped. Verified progress is kept. Run this downloader again to continue.'); exit 1 }"
set "downloadResult=%ERRORLEVEL%"
if /I not "%~1"=="--no-pause" pause
exit /b %downloadResult%
:PowerShellSource
# Release downloader v2. All generated files stay beside this CMD, never in TEMP.
$manifest = @'
__MANIFEST__
'@ | ConvertFrom-Json
$baseUrl = '__BASE_URL__'
$directory = [IO.Path]::GetDirectoryName($env:SOMEPHYLLOSCOPUS_DOWNLOADER)
$output = Join-Path $directory $manifest.file
$partialZip = "$output.downloading"
$curl = (Get-Command curl.exe -ErrorAction Stop).Source

function Get-Sha256([string] $path) {
    $algorithm = [Security.Cryptography.SHA256]::Create()
    $file = [IO.File]::OpenRead($path)
    try { [BitConverter]::ToString($algorithm.ComputeHash($file)).Replace('-', '').ToLowerInvariant() }
    finally { $file.Dispose(); $algorithm.Dispose() }
}

function Test-Part([string] $path, $part) {
    return ((Test-Path -LiteralPath $path -PathType Leaf) -and
        (Get-Item -LiteralPath $path).Length -eq $part.bytes -and
        (Get-Sha256 $path) -eq $part.sha256)
}

function Get-SegmentHash([IO.Stream] $stream, [long] $count) {
    $algorithm = [Security.Cryptography.SHA256]::Create()
    $buffer = New-Object byte[] (4 * 1024 * 1024)
    try {
        while ($count -gt 0) {
            $read = $stream.Read($buffer, 0, [int][Math]::Min($count, $buffer.Length))
            if ($read -eq 0) { throw 'Unexpected end of saved download.' }
            [void]$algorithm.TransformBlock($buffer, 0, $read, $buffer, 0)
            $count -= $read
        }
        [void]$algorithm.TransformFinalBlock($buffer, 0, 0)
        return [BitConverter]::ToString($algorithm.Hash).Replace('-', '').ToLowerInvariant()
    } finally { $algorithm.Dispose() }
}

function Receive-Part($part, [string] $partPath) {
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        if (Test-Part $partPath $part) { return }
        if (Test-Path -LiteralPath $partPath) {
            if ((Get-Item -LiteralPath $partPath).Length -ge $part.bytes) {
                Write-Host 'Incomplete or damaged cached part: downloading this part again.'
                Remove-Item -LiteralPath $partPath
            }
        }
        Write-Host "Downloading $($part.file), attempt $attempt/3"
        # Each retry resumes the saved bytes; curl's internal retry can rewind them.
        & $curl -q --fail --location --connect-timeout 20 --speed-limit 1024 --speed-time 60 --continue-at - --output $partPath "$baseUrl/$($part.file)"
        $code = $LASTEXITCODE
        if (Test-Part $partPath $part) { return }
        if ($code -eq 33) {
            # Server refused Range; restart only this generated temporary part.
            if (Test-Path -LiteralPath $partPath) { Remove-Item -LiteralPath $partPath }
        }
        Write-Warning "Transfer incomplete or SHA-256 mismatch for $($part.file) (curl $code)."
        if ($attempt -lt 3) { Start-Sleep -Seconds 2 }
    }
    throw "Could not verify $($part.file). Keep the downloader and .downloading files together, then retry."
}

Write-Host 'SomePhylloscopus v0.1.0 - Windows NVIDIA download and repair'
Write-Host "Save location: $directory"
Write-Host 'The .part files are DATA FRAGMENTS. Do not open or extract them separately.'
Write-Host 'If you already downloaded parts, put them beside this CMD. They will be checked and reused.'
Write-Host 'To use another drive, move this CMD and its saved files together to that drive.'
Write-Host 'This download needs up to 7.2 GiB; allow at least 20 GB including extraction.'

if (Test-Path -LiteralPath $output) {
    if (Test-Part $output $manifest) {
        Write-Host "Already verified: $output"
        return
    }
    throw "A different ZIP already exists at $output. Move it aside before downloading."
}

$zip = $null
try {
    # Exclusive access also prevents two downloaders from damaging the same file.
    $zip = [IO.File]::Open($partialZip, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    [long]$offset = 0
    foreach ($part in $manifest.parts) {
        $partPath = Join-Path $directory ($part.file + '.downloading')
        if ($zip.Length -ge ($offset + $part.bytes)) {
            $zip.Position = $offset
            Write-Host "Checking saved $($part.file)"
            if ((Get-SegmentHash $zip $part.bytes) -eq $part.sha256) {
                $offset += $part.bytes
                # This can remain if interrupted after append but before cleanup.
                if (Test-Path -LiteralPath $partPath) { Remove-Item -LiteralPath $partPath }
                continue
            }
        }
        # Only retain fully verified prefixes of our own assembly file.
        $zip.SetLength($offset)
        $zip.Position = $offset
        $manualPart = Join-Path $directory $part.file
        if (Test-Part $manualPart $part) {
            Write-Host "Using verified existing $($part.file)"
            $source = $manualPart
        } else {
            if (Test-Path -LiteralPath $manualPart) {
                Write-Warning "Existing $($part.file) failed size/hash checks. It is preserved; a fresh copy will be downloaded."
            }
            Receive-Part $part $partPath
            $source = $partPath
        }
        $partStream = [IO.File]::OpenRead($source)
        try { $partStream.CopyTo($zip, 4 * 1024 * 1024) } finally { $partStream.Dispose() }
        $zip.Flush($true)
        $offset += $part.bytes
        if ($source -eq $partPath) { Remove-Item -LiteralPath $partPath }
        Write-Host ('Verified and assembled: {0:N2} / {1:N2} GiB' -f ($offset / 1GB), ($manifest.bytes / 1GB))
    }
    $zip.SetLength($manifest.bytes)
    $zip.Dispose()
    $zip = $null
    Write-Host 'Verifying complete ZIP SHA-256...'
    if (-not (Test-Part $partialZip $manifest)) { throw 'Complete ZIP verification failed. Retry to check saved parts.' }
    [IO.File]::Move($partialZip, $output)
    Write-Host "Verified complete ZIP: $output"
    Write-Host "SHA-256: $($manifest.sha256)"
    Write-Host 'Extract the COMPLETE .zip, then double-click the app EXE inside.'
    Write-Host 'After extraction and successful launch, you may delete the ZIP and any manually downloaded parts.'
} finally {
    if ($zip) { $zip.Dispose() }
    # Failed/cancelled transfers are deliberately kept for the next run.
}
