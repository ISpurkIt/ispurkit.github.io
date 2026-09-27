# Builds YT-DLP Studio for Windows: dist\YT-DLP Studio\ (portable) and, if Inno Setup is installed,
# dist\YT-DLP-Studio-Setup-<version>.exe.   Run build.bat, or:
#   powershell -ExecutionPolicy Bypass -File desktop\build.ps1
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot)          # yt-dlp-gui\

$venv = '.venv-build'
if (-not (Test-Path "$venv\Scripts\python.exe")) {
    Write-Host 'Creating the build environment...'
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.12 -m venv $venv
        if ($LASTEXITCODE) { & py -3 -m venv $venv }
    } else {
        & python -m venv $venv
    }
    if ($LASTEXITCODE) { throw 'Python 3.10+ is required: https://www.python.org/downloads/' }
}
$py = Resolve-Path "$venv\Scripts\python.exe"
& $py -m pip install --disable-pip-version-check -q -U pip
& $py -m pip install --disable-pip-version-check -q -U -r desktop\requirements-desktop.txt
if ($LASTEXITCODE) { throw 'pip install failed' }

if (-not (Test-Path 'desktop\bin\ffmpeg.exe') -or -not (Test-Path 'desktop\bin\deno.exe')) {
    & (Join-Path $PSScriptRoot 'fetch-tools.ps1')
}

& $py -m PyInstaller desktop\yt-dlp-studio.spec --noconfirm --clean --distpath dist --workpath build
if ($LASTEXITCODE) { throw 'PyInstaller failed' }

$exe = 'dist\YT-DLP Studio\YT-DLP Studio.exe'
$report = Join-Path $PWD 'dist\self-test.json'
$test = Start-Process -FilePath $exe -ArgumentList '--self-test', "`"$report`"" -Wait -PassThru
Get-Content $report
if ($test.ExitCode -ne 0) { throw 'Self-test failed' }

$version = & $py -c "from backend.version import APP_VERSION; print(APP_VERSION)"
$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
          "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($iscc) {
    & $iscc "/DAppVersion=$version" desktop\installer.iss
    if ($LASTEXITCODE) { throw 'Inno Setup failed' }
} else {
    Write-Host 'Inno Setup 6 is not installed - skipping the installer (https://jrsoftware.org/isdl.php).'
}
Write-Host "`nDone: $(Resolve-Path 'dist')"
