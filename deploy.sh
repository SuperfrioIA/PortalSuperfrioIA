#!/usr/bin/env bash
# Hub SuperFrio & Icestar - deploy na VM (git pull + build + up)
# Uso:  ./deploy.sh             (git pull + build + up -d + status)
#       ./deploy.sh --no-cache  (force rebuild sem cache)
#       ./deploy.sh --down      (para o container)
#       ./deploy.sh --reset     (DESTROI volume data/ - cuidado, apaga o .db)
#       ./deploy.sh --logs      (segue os logs do container ja rodando)

set -e
cd "$(dirname "$0")"

case "${1:-}" in
  --logs)
    docker compose logs -f hub
    exit 0
    ;;
  --down)
    echo "[stop] parando container..."
    docker compose down
    exit 0
    ;;
  --reset)
    echo "[reset] parando container e apagando volume data/ ..."
    docker compose down
    rm -f data/*.db*
    echo "[reset] .db removido. Proximo up vai re-seedar."
    exit 0
    ;;
esac

if [ -z "${SUPERFRIO_JWT_SECRET:-}" ]; then
  echo "[aviso] SUPERFRIO_JWT_SECRET nao definido no ambiente - usando o que estiver no .env (ou o default de dev)"
fi

echo "[pull] git pull..."
git pull

echo "[build] docker compose build..."
if [ "${1:-}" = "--no-cache" ]; then
  docker compose build --no-cache
else
  docker compose build
fi

echo "[up] subindo container em background..."
docker compose up -d

sleep 2

echo ""
echo "[status]"
docker compose ps

echo ""
echo "[ok] Hub atualizado."
echo "     Logs:   ./deploy.sh --logs"
echo "     Parar:  ./deploy.sh --down"
