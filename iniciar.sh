#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

VENV_PY="$(pwd)/.venv/bin/python"

# Verifica se o Python da .venv está realmente isolado do Python do sistema.
if [ ! -x "$VENV_PY" ] || ! "$VENV_PY" -c 'import sys, pip; assert sys.prefix != sys.base_prefix' >/dev/null 2>&1; then
  if [ -d .venv ]; then
    ANTIGA=".venv-antiga-$(date +%Y%m%d%H%M%S)"
    mv .venv "$ANTIGA"
    echo "Ambiente antigo inválido preservado em $ANTIGA"
  fi
  echo 'Criando ambiente Python isolado (.venv)...'
  python3 -m venv .venv || {
    echo 'Falha ao criar .venv. Instale: sudo apt install python3-venv python3-pip'
    exit 1
  }
fi

if ! "$VENV_PY" -c 'import fastapi,uvicorn,jinja2,argon2,PIL,reportlab,multipart,itsdangerous,xlsxwriter,qrcode' 2>/dev/null; then
  echo 'Instalando dependências na .venv... (internet necessária na primeira execução)'
  "$VENV_PY" -m pip install -r requirements.txt
fi

if [ ! -f .env ]; then
  umask 077
  printf 'export SOS_SECRET_KEY="%s"\n' "$("$VENV_PY" -c 'import secrets;print(secrets.token_hex(48))')" > .env
  echo 'Chave de sessão criada em .env (arquivo privado).'
fi

# shellcheck disable=SC1091
source .env

if [ "$#" -eq 0 ]; then
  echo 'SOS Patinhas em http://127.0.0.1:8000'
  exec "$VENV_PY" app.py
else
  exec "$VENV_PY" app.py "$@"
fi
