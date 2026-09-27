# Downloads the programs bundled into the Windows build: ffmpeg/ffprobe and deno.
#   powershell -ExecutionPolicy Bypass -File desktop\fetch-tools.ps1
param([string]$Dest = (Join-Path $PSScriptRoot 'bin'))
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # Invoke-WebRequest is painfully slow with the progress bar
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$tmp = Join-Path ([IO.Path]::GetTempPath()) 'yt-dlp-studio-tools'
Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $tmp, $Dest | Out-Null

# ffmpeg: the builds maintained by the yt-dlp project (patched for yt-dlp). The "shared" variant keeps
# ffmpeg.exe and ffprobe.exe small and shares one set of DLLs between them.
$ffmpeg = 'https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl-shared.zip'
Write-Host "Downloading $ffmpeg"
Invoke-WebRequest $ffmpeg -OutFile "$tmp\ffmpeg.zip"
Expand-Archive "$tmp\ffmpeg.zip" "$tmp\ffmpeg" -Force
$root = Get-ChildItem "$tmp\ffmpeg" -Directory | Select-Object -First 1
Copy-Item "$($root.FullName)\bin\ffmpeg.exe", "$($root.FullName)\bin\ffprobe.exe", "$($root.FullName)\bin\*.dll" $Dest
Copy-Item "$($root.FullName)\LICENSE.txt" (Join-Path $Dest 'FFMPEG-LICENSE.txt') -ErrorAction SilentlyContinue

# deno: the JavaScript runtime yt-dlp uses to unlock all YouTube formats
$deno = 'https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip'
Write-Host "Downloading $deno"
Invoke-WebRequest $deno -OutFile "$tmp\deno.zip"
Expand-Archive "$tmp\deno.zip" $Dest -Force

& (Join-Path $Dest 'ffmpeg.exe') -hide_banner -version | Select-Object -First 1
& (Join-Path $Dest 'deno.exe') --version | Select-Object -First 1
Remove-Item $tmp -Recurse -Force
