#!/usr/bin/env bash
# Comando forçado da chave de deploy da CI (Y1.4). Instalado no node 2 como
# /usr/local/bin/ayanami-ci-deploy (root:root 0755) e amarrado à chave pública da CI no
# ~ayanami/.ssh/authorized_keys:
#
#   restrict,command="/usr/local/bin/ayanami-ci-deploy" ssh-ed25519 AAAA… ayanami-ci
#
# A chave não abre shell: só aceita, em $SSH_ORIGINAL_COMMAND, um destes pedidos:
#
#   deploy <sha de 40 hex>   # código em <sha> (fetch + merge --ff-only) e
#                            # deploy.sh --tag <sha> --sem-git --sem-build (imagens do ghcr)
#   saude                    # /saude respondeu e banco == "ok" (o `ok` geral pode ser false
#                            # enquanto faltam segredos de terceiros)
#   app <vc> <sha256> <b64url do versao.json>   # APK da Condessa no stdin (M1.7, DSC7):
#                            # vai para $AYANAMI_DIR/dados/app/condessa-<vc>.apk + versao.json
#                            # (mv atômico, APK antes do JSON; mantém os 3 APKs mais novos)
set -euo pipefail

AYANAMI_DIR="${AYANAMI_DIR:-/opt/ayanami}"
URL_SAUDE="http://127.0.0.1:8740/saude"
APP_MAX_BYTES=$((30 * 1024 * 1024))   # 30 MiB
APP_MANTER=3

pedido="${SSH_ORIGINAL_COMMAND:-}"
read -r verbo arg resto <<<"$pedido" || true

case "${verbo:-}" in
  deploy)
    if [ -n "${resto:-}" ] || ! [[ "${arg:-}" =~ ^[0-9a-f]{40}$ ]]; then
      echo "recusado: uso 'deploy <sha de 40 hex>'" >&2
      exit 2
    fi
    exec 9>"$AYANAMI_DIR/.git/ci-deploy.lock"
    flock -w 600 9 || { echo "outro deploy em andamento" >&2; exit 1; }
    git -C "$AYANAMI_DIR" fetch --quiet origin main
    git -C "$AYANAMI_DIR" merge --ff-only --quiet "$arg"
    exec "$AYANAMI_DIR/deploy/ayanami/host/deploy.sh" --tag "$arg" --sem-git --sem-build
    ;;
  saude)
    [ -z "${arg:-}" ] || { echo "recusado: 'saude' não leva argumento" >&2; exit 2; }
    curl -fsS --max-time 10 "$URL_SAUDE" | python3 -c '
import json, sys
s = json.load(sys.stdin)
print("banco=%s ok=%s faltando=%s" % (s.get("banco"), s.get("ok"), s.get("faltando")))
sys.exit(0 if s.get("banco") == "ok" else 1)
'
    ;;
  app)
    # app <vc 1..9 dígitos> <sha256 64 hex> <b64url ≤ 4096>; APK no stdin.
    read -r _ vc sha b64 resto <<<"$pedido" || true
    if [ -n "${resto:-}" ] || ! [[ "${vc:-}" =~ ^[1-9][0-9]{0,8}$ ]] \
      || ! [[ "${sha:-}" =~ ^[0-9a-f]{64}$ ]] || ! [[ "${b64:-}" =~ ^[A-Za-z0-9_-]{1,4096}$ ]]; then
      echo "recusado: uso 'app <versionCode> <sha256> <versao.json em base64url>' (APK no stdin)" >&2
      exit 2
    fi
    app_dir="$AYANAMI_DIR/dados/app"
    umask 022
    mkdir -p "$app_dir"
    exec 8>"$AYANAMI_DIR/dados/app.lock"
    flock -w 600 8 || { echo "recusado: outra publicação do app em andamento" >&2; exit 2; }
    tmp_apk="$app_dir/.tmp-$vc.apk"
    tmp_json="$app_dir/.tmp-$vc.json"
    trap 'rm -f "$tmp_apk" "$tmp_json"' EXIT
    recusa() { rm -f "$tmp_apk" "$tmp_json"; echo "recusado: $1" >&2; exit 2; }
    head -c $((APP_MAX_BYTES + 1)) >"$tmp_apk" || recusa "falha ao ler o APK do stdin"
    tamanho=$(stat -c %s "$tmp_apk") || recusa "falha ao medir o APK"
    [ "$tamanho" -gt 0 ] || recusa "APK vazio"
    [ "$tamanho" -le "$APP_MAX_BYTES" ] || recusa "APK maior que 30 MiB"
    sha_lido=$(sha256sum "$tmp_apk" | cut -d' ' -f1) || recusa "falha no sha256"
    [ "$sha_lido" = "$sha" ] || recusa "sha256 do APK não confere"
    motivo=$(python3 -c '
import base64, json, re, sys
b64, vc, sha, tamanho, atual, saida = sys.argv[1:]
vc, tamanho = int(vc), int(tamanho)
try:
    obj = json.loads(base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4)).decode("utf-8"))
except Exception:
    sys.exit("versao.json ilegível")
chaves = {"versionCode", "versionName", "sha256", "bytes", "minimo", "notas", "publicado", "cert_sha256"}
if not isinstance(obj, dict) or set(obj) != chaves:
    sys.exit("versao.json com chaves erradas")
def inteiro(v):
    return isinstance(v, int) and not isinstance(v, bool)
if not inteiro(obj["versionCode"]) or obj["versionCode"] != vc:
    sys.exit("versionCode diferente do argumento")
if obj["sha256"] != sha:
    sys.exit("sha256 do versao.json diferente do argumento")
if not inteiro(obj["bytes"]) or obj["bytes"] != tamanho:
    sys.exit("bytes do versao.json diferente do APK")
if not inteiro(obj["minimo"]) or not 1 <= obj["minimo"] <= vc:
    sys.exit("minimo inválido")
if not isinstance(obj["versionName"], str) or not obj["versionName"]:
    sys.exit("versionName inválido")
if not isinstance(obj["notas"], str) or not isinstance(obj["publicado"], str):
    sys.exit("notas/publicado inválidos")
if not isinstance(obj["cert_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", obj["cert_sha256"]):
    sys.exit("cert_sha256 inválido")
publicado = 0
try:
    with open(atual, encoding="utf-8") as f:
        v = json.load(f).get("versionCode")
    if inteiro(v):
        publicado = v
except (OSError, ValueError, AttributeError):
    pass
if vc <= publicado:
    sys.exit("versionCode %d não é maior que o publicado (%d)" % (vc, publicado))
with open(saida, "w", encoding="utf-8") as f:
    json.dump(obj, f, ensure_ascii=False, indent=2)
    f.write("\n")
' "$b64" "$vc" "$sha" "$tamanho" "$app_dir/versao.json" "$tmp_json" 2>&1) || recusa "$motivo"
    chmod 0644 "$tmp_apk" "$tmp_json"
    mv -f "$tmp_apk" "$app_dir/condessa-$vc.apk"
    mv -f "$tmp_json" "$app_dir/versao.json"
    find "$app_dir" -maxdepth 1 -type f -name 'condessa-*.apk' -printf '%f\n' \
      | sed -n 's/^condessa-\([0-9]\{1,9\}\)\.apk$/\1/p' | sort -n -r | tail -n +$((APP_MANTER + 1)) \
      | while read -r velho; do rm -f "$app_dir/condessa-$velho.apk"; done
    echo "publicado vc=$vc bytes=$tamanho"
    ;;
  *)
    echo "recusado: esta chave só aceita 'deploy <sha>', 'saude' ou 'app <vc> <sha256> <b64url>'" >&2
    exit 2
    ;;
esac
