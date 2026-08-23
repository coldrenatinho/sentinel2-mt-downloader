#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:?Uso: build_arch_package.sh VERSION}"
OUT="$ROOT/release"
WORK="/tmp/sentinel2-mt-arch-package"

if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z]+(\.[0-9A-Za-z]+)*)?$ ]]; then
  echo "Versão inválida: use o formato X.Y.Z ou X.Y.Z-sufixo" >&2
  exit 2
fi
PKG_VERSION="${VERSION//-/.}"

rm -rf "$WORK"
mkdir -p "$WORK"
install -m755 "$OUT/sentinel2-mt-linux-x86_64" "$WORK/sentinel2-mt"
install -m644 "$OUT/sentinel2-mt-config.yaml" "$WORK/config.yaml"
install -m644 "$OUT/sentinel2-mt.desktop" "$WORK/sentinel2-mt.desktop"
install -m755 "$OUT/sentinel2-mt-wrapper.sh" "$WORK/sentinel2-mt-wrapper.sh"
sed \
  -e "s/@VERSION@/$VERSION/g" \
  -e "s/@PKGVER@/$PKG_VERSION/g" \
  "$ROOT/packaging/arch/PKGBUILD.ci" >"$WORK/PKGBUILD"

useradd --create-home builder
chown -R builder:builder "$WORK"
mapfile -t PACOTES < <(
  runuser -u builder -- bash -lc "cd '$WORK' && makepkg --packagelist"
)
runuser -u builder -- bash -lc "cd '$WORK' && makepkg --noconfirm --cleanbuild --nodeps"
if (( ${#PACOTES[@]} == 0 )); then
  echo "makepkg não informou nenhum artefato" >&2
  exit 1
fi
for pacote in "${PACOTES[@]}"; do
  if [[ ! -f "$pacote" ]]; then
    echo "Artefato esperado não foi gerado: $pacote" >&2
    exit 1
  fi
  cp "$pacote" "$OUT/"
done
echo "Pacote Arch Linux gerado em: $OUT"
