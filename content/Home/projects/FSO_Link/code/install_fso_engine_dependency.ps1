$ErrorActionPreference = "Stop"

$repoUrl = "https://github.com/Sang-rok/FSO-simulator.git"
$target = Join-Path $PSScriptRoot "external\FSO-simulator"

if (Test-Path (Join-Path $target ".git")) {
    git -C $target pull --ff-only
} else {
    New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null
    git clone $repoUrl $target
}

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

& $python -m pip install -r (Join-Path $target "requirements.txt")
