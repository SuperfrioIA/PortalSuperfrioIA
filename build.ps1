# Portal SuperFrio - build & deploy via Docker
# Uso:  .\build.ps1           (build + up -d + logs iniciais)
#       .\build.ps1 -NoCache  (force rebuild sem cache)
#       .\build.ps1 -Down     (para o container)
#       .\build.ps1 -Reset    (DESTROI volume data/ - cuidado, apaga o .db)
#       .\build.ps1 -Logs     (segue os logs do container ja rodando)

param(
    [switch]$NoCache,
    [switch]$Down,
    [switch]$Reset,
    [switch]$Logs
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

# Verifica docker
$dockerCheck = docker version --format '{{.Server.Version}}' 2>$null
if (-not $dockerCheck) {
    throw "Docker nao esta disponivel. Inicie o Docker Desktop."
}

if ($Logs) {
    docker compose logs -f portal
    exit 0
}

if ($Down) {
    Write-Host "[stop] parando container..."
    docker compose down
    exit 0
}

if ($Reset) {
    Write-Host "[reset] parando container e apagando volume data/ ..."
    docker compose down
    if (Test-Path "data") {
        Remove-Item -Recurse -Force "data\*.db*" -ErrorAction SilentlyContinue
        Write-Host "[reset] .db removido. Proximo build vai re-seedar."
    }
    exit 0
}

if (-not $env:SUPERFRIO_JWT_SECRET) {
    Write-Host "[aviso] SUPERFRIO_JWT_SECRET nao definido - usando default dev-secret-change-me"
    Write-Host "        em prod, defina antes:  `$env:SUPERFRIO_JWT_SECRET = 'sua-chave-forte'"
}

Write-Host "[build] docker compose build..."
if ($NoCache) {
    docker compose build --no-cache
} else {
    docker compose build
}
if (-not $?) { throw "falha no build" }

Write-Host "[up] subindo container em background..."
docker compose up -d
if (-not $?) { throw "falha no up" }

Start-Sleep -Seconds 2

Write-Host ""
Write-Host "[status]"
docker compose ps

Write-Host ""
Write-Host "[ok] Portal em http://127.0.0.1:8000"
Write-Host "     Logs:   .\build.ps1 -Logs"
Write-Host "     Parar:  .\build.ps1 -Down"
