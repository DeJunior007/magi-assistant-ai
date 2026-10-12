#!/usr/bin/env bash
# Postgres DESCARTÁVEL dos testes `pg` da Ayanami (dono: Y0.3; tasks, regra 7).
#
#   deploy/ayanami/pg-teste.sh subir      # sobe ayanami-pg-teste em 127.0.0.1:54340 e espera ficar pronto
#   deploy/ayanami/pg-teste.sh dsn        # imprime a linha `export AYANAMI_TEST_DSN=...`
#   deploy/ayanami/pg-teste.sh derrubar   # para o contêiner (--rm: some junto com os dados, que são tmpfs)
#   deploy/ayanami/pg-teste.sh estado
#
# Uso típico:  eval "$(deploy/ayanami/pg-teste.sh subir)" && uv run pytest -q tests/ayanami
#
# Só mexe no contêiner `ayanami-pg-teste`. Nunca toca no `magi-pg` (porta 54329) nem em volume:
# os dados ficam em tmpfs e o contêiner é `--rm`. Senha fixa e falsa: é só para teste local.
set -euo pipefail

NOME="ayanami-pg-teste"
PORTA="54340"
IMAGEM="pgvector/pgvector:pg16"
USUARIO="ayanami"
SENHA="teste"
BASE="ayanami_teste"
DSN="postgresql://${USUARIO}:${SENHA}@127.0.0.1:${PORTA}/${BASE}"

rodando() { [ "$(docker ps -q --filter "name=^${NOME}\$")" != "" ]; }

subir() {
    if ! rodando; then
        docker run -d --rm --name "$NOME" \
            -p "127.0.0.1:${PORTA}:5432" \
            --tmpfs /var/lib/postgresql/data:rw \
            -e POSTGRES_USER="$USUARIO" -e POSTGRES_PASSWORD="$SENHA" -e POSTGRES_DB="$BASE" \
            "$IMAGEM" -c fsync=off -c synchronous_commit=off -c full_page_writes=off >/dev/null
    fi
    for _ in $(seq 1 60); do
        # pronto = aceita conexão TCP (o initdb sobe um servidor só por socket antes)
        if docker exec "$NOME" pg_isready -q -h 127.0.0.1 -U "$USUARIO" -d "$BASE" 2>/dev/null; then
            echo "export AYANAMI_TEST_DSN=${DSN}"
            return 0
        fi
        sleep 0.5
    done
    echo "pg-teste: ${NOME} não ficou pronto em 30 s" >&2
    return 1
}

derrubar() {
    if rodando; then
        docker stop "$NOME" >/dev/null
        echo "pg-teste: ${NOME} parado (e removido, --rm)" >&2
    else
        echo "pg-teste: ${NOME} não está rodando" >&2
    fi
}

case "${1:-}" in
    subir) subir ;;
    derrubar) derrubar ;;
    dsn) echo "export AYANAMI_TEST_DSN=${DSN}" ;;
    estado) if rodando; then echo "rodando em 127.0.0.1:${PORTA}"; else echo "parado"; exit 1; fi ;;
    *) echo "uso: $0 subir|derrubar|dsn|estado" >&2; exit 2 ;;
esac
