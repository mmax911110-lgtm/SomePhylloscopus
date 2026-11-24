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
{
  "file": "SomePhylloscopus-v0.1.0-Windows-NVIDIA.zip",
  "bytes": 6093329218,
  "sha256": "5f044a594a641399ff77438849e7225b93aad0612d6ae1d741ca8181670cd62c",
  "parts": [
    {
      "file": "SomePhylloscopus-v0.1.0-Windows-NVIDIA.zip.part01a",
      "bytes": 268435456,
      "sha256": "0c341d5f5dc2820be383636159c3af929e6fedde9961f7baba86a049d71f73e7"
    },
    {
      "file": "SomePhylloscopus-v0.1.0-Windows-NVIDIA.zip.part01b",
      "bytes": 268435456,
      "sha256": "2b555c224603331787bb0bc700739ee9fcae51c8bd13b4ffe64f163b13d3a22e"
    },
    {
      "file": "SomePhylloscopus-v0.1.0-Windows-NVIDIA.zip.part01c",
      "bytes": 268435456,
      "sha256": "78bb376522881f0370861d3ecc2711c40f04f9190e5bef27d17177db197e1a6f"
    },
    {
      "file": "SomePhylloscopus-v0.1.0-Windows-NVIDIA.zip.part01d",
      "bytes": 268435456,
      "sha256": "f5aa6568ebc96bf273254ccd074e858dc0009ebd27b838ebb0c4463d87c2665f"
    },
    {
      "file": "SomePhylloscopus-v0.1.0-Windows-NVIDIA.zip.part01e",
      "bytes": 268435456,
      "sha256": "bf8d49cf3e5a394c15bee44039c578f0814940f36f64431399f496bd397dcb42"
    },
    {
      "file": "SomePhylloscopus-v0.1.0-Windows-NVIDIA.zip.part01f",
      "bytes": 268435456,
      "sha256": "1600b47945709a5354377de3d2a72f14b41e78d935ed80d46c05136712d198b7"
    },
    {
      "file": "SomePhylloscopus-v0.1.0-Windows-NVIDIA.zip.part02",
      "bytes": 1610612736,
      "sha256": "cbec393ef18ea3c1ea586e97848f9b93eb57626694ba55cd4e53f776beea5357"
    },
    {
      "file": "SomePhylloscopus-v0.1.0-Windows-NVIDIA.zip.part03",
      "bytes": 1610612736,
      "sha256": "5380c0b25440d1c1e022bdbc7668b38e6c53e0cb12ac395bd819c3cf3ac5fbe7"
    },
    {
      "file": "SomePhylloscopus-v0.1.0-Windows-NVIDIA.zip.part04",
      "bytes": 1261491010,
      "sha256": "d79b52b32672050b7c042dd98fb1e4506f66ad268502aaf3799d9ad7abc26644"
    }
  ]
}
'@ | ConvertFrom-Json
$baseUrl = 'https://github.com/mmax911110-lgtm/SomePhylloscopus/releases/download/v0.1.0'
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
