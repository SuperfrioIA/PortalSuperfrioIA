# Portal SuperFrio - dev local
# Uso:  .\run.ps1            (sobe na porta 8000, so localhost)
#       .\run.ps1 -Port 8080 (porta custom)
#       .\run.ps1 -NoReload  (sem auto-reload, mais proximo de prod)
#       .\run.ps1 -Network   (expoe na rede - outros PCs acessam pelo IP)

param(
    [int]$Port = 8000,
    [switch]$NoReload,
    [switch]$Network
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

if (-not (Test-Path ".venv")) {
    Write-Host "[setup] criando .venv..."
    python -m venv .venv
    if (-not $?) { throw "falha ao criar .venv" }
}

$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

Write-Host "[setup] instalando dependencias..."
& $py -m pip install --disable-pip-version-check -q -r requirements.txt
if (-not $?) { throw "falha no pip install" }

if (-not $env:SUPERFRIO_JWT_SECRET) {
    Write-Host "[aviso] SUPERFRIO_JWT_SECRET nao definido - usando default dev-secret-change-me"
}

$bindHost = if ($Network) { "0.0.0.0" } else { "127.0.0.1" }
if ($Network) {
    $ip = (Get-NetIPAddress -AddressFamily IPv4 -PrefixOrigin Dhcp -ErrorAction SilentlyContinue | Select-Object -First 1).IPAddress
    if (-not $ip) { $ip = "<seu-ip>" }
    Write-Host "[run] uvicorn em http://0.0.0.0:$Port (Ctrl+C para parar)"
    Write-Host "[rede] compartilhe: http://${ip}:$Port"
} else {
    Write-Host "[run] uvicorn em http://127.0.0.1:$Port (Ctrl+C para parar)"
}
$args = @("-m", "uvicorn", "backend.main:app", "--port", $Port, "--host", $bindHost)
if (-not $NoReload) { $args += "--reload" }

& $py @args
