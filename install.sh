#!/usr/bin/env bash
# Instalador de una línea para macOS y Linux.
#
#   curl -fsSL https://raw.githubusercontent.com/tacosandtypescript-debug/StreamLabsTikTokStreamKeyGenerator/main/install.sh | bash
#
# Opciones:
#   bash install.sh            -> última versión
#   bash install.sh 2.1.2      -> una versión concreta
#   ALLOW_UNVERIFIED=1 bash install.sh   -> continuar aunque no haya checksum
#
# Descarga la release, verifica su checksum y la instala en tu carpeta de
# usuario. No necesita permisos de administrador.

set -euo pipefail

REPO="tacosandtypescript-debug/StreamLabsTikTokStreamKeyGenerator"
APP_NAME="StreamLabsTikTokStreamKeyGenerator"
VERSION="${1:-latest}"
ALLOW_UNVERIFIED="${ALLOW_UNVERIFIED:-0}"

say() { printf '\033[36m==> %s\033[0m\n' "$1"; }
warn() { printf '\033[33mAviso: %s\033[0m\n' "$1"; }
die() { printf '\033[31mError: %s\033[0m\n' "$1" >&2; exit 1; }

command -v curl >/dev/null 2>&1 || die "hace falta 'curl'"

printf '\n  StreamLabs TikTok Stream Key Generator - instalador\n'
printf '  ------------------------------------------------\n'

# ------------------------------------------------------------ 1. Plataforma --
os="$(uname -s)"
arch="$(uname -m)"
case "$os" in
  Darwin) pattern="macos"; platform="macOS ($arch)" ;;
  Linux)  pattern="linux"; platform="Linux ($arch)" ;;
  *) die "sistema no soportado: $os" ;;
esac

if [ "$VERSION" = "latest" ]; then
  api="https://api.github.com/repos/$REPO/releases/latest"
else
  api="https://api.github.com/repos/$REPO/releases/tags/v${VERSION#v}"
fi

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

say "Consultando la release..."
curl -fsSL "$api" -o "$workdir/release.json" || die "no se pudo consultar la release en GitHub"

json_field() {
  # $1 = nombre del campo; imprime el primer valor encontrado
  grep -o "\"$1\": *\"[^\"]*\"" "$workdir/release.json" | head -n1 | sed 's/.*: *"//; s/"$//'
}

tag="$(json_field tag_name)"
[ -n "$tag" ] || die "la respuesta de GitHub no tiene el formato esperado"

# Nombre del paquete: se elige por plataforma y, en macOS, por arquitectura.
asset_name="$(grep -o '"name": *"[^"]*"' "$workdir/release.json" | sed 's/.*: *"//; s/"$//' \
  | grep -E "\.zip$" | grep -E -- "-${pattern}-" | grep -E -- "-${arch}-|win-|linux-" | head -n1)"
[ -n "$asset_name" ] || die "la release $tag no incluye un paquete para $platform"

asset_url="$(grep -o '"browser_download_url": *"[^"]*"' "$workdir/release.json" | sed 's/.*: *"//; s/"$//' \
  | grep -F "/$asset_name" | head -n1)"
[ -n "$asset_url" ] || die "no se pudo obtener la URL de descarga de $asset_name"
checksums_url="$(grep -o '"browser_download_url": *"[^"]*"' "$workdir/release.json" | sed 's/.*: *"//; s/"$//' \
  | grep -F "/SHA256SUMS.txt" | head -n1)"

say "Versión $tag"

# -------------------------------------------------------------- 2. Descarga --
say "Descargando $asset_name..."
curl -fsSL "$asset_url" -o "$workdir/$asset_name" || die "falló la descarga"

# ---------------------------------------------------------- 3. Verificación --
expected=""
if [ -n "$checksums_url" ]; then
  say "Verificando el checksum..."
  curl -fsSL "$checksums_url" -o "$workdir/SHA256SUMS.txt" || true
  expected="$(grep -F "$asset_name" "$workdir/SHA256SUMS.txt" 2>/dev/null | awk '{print $1}' | head -n1 || true)"
fi

if [ -n "$expected" ]; then
  if command -v sha256sum >/dev/null 2>&1; then
    actual="$(sha256sum "$workdir/$asset_name" | awk '{print $1}')"
  else
    actual="$(shasum -a 256 "$workdir/$asset_name" | awk '{print $1}')"
  fi
  if [ "$actual" != "$expected" ]; then
    die "el checksum NO coincide: la descarga se ha descartado.
  esperado: $expected
  obtenido: $actual"
  fi
  say "Checksum correcto."
elif [ "$ALLOW_UNVERIFIED" = "1" ]; then
  warn "sin checksum publicado; se continúa por ALLOW_UNVERIFIED=1"
else
  die "no se pudo verificar la descarga (la release no publica SHA256SUMS.txt o no incluye este archivo).
Si asumes el riesgo, repite con: ALLOW_UNVERIFIED=1"
fi

# ----------------------------------------------------------- 4. Descomprimir --
extract_zip() {
  if command -v unzip >/dev/null 2>&1; then
    unzip -q "$1" -d "$2"
  elif command -v python3 >/dev/null 2>&1; then
    python3 -m zipfile -e "$1" "$2"
  else
    die "hace falta 'unzip' (o python3) para descomprimir"
  fi
}
mkdir -p "$workdir/extract"
extract_zip "$workdir/$asset_name" "$workdir/extract"

# ------------------------------------------------------------ 5. Instalar --
if [ "$os" = "Darwin" ]; then
  app_path="$workdir/extract/$APP_NAME.app"
  [ -d "$app_path" ] || die "el paquete no contiene $APP_NAME.app"
  install_dir="/Applications"
  [ -w "$install_dir" ] || install_dir="$HOME/Applications"
  say "Instalando en $install_dir..."
  mkdir -p "$install_dir"
  rm -rf "${install_dir:?}/$APP_NAME.app"
  cp -R "$app_path" "$install_dir/" || die "no se pudo copiar a $install_dir"
  xattr -dr com.apple.quarantine "$install_dir/$APP_NAME.app" 2>/dev/null || true
  installed="$install_dir/$APP_NAME.app"
else
  install_dir="$HOME/.local/share/$APP_NAME"
  say "Instalando en $install_dir..."
  rm -rf "$install_dir"
  mkdir -p "$install_dir"
  cp -R "$workdir/extract/." "$install_dir/"
  installed="$install_dir/$APP_NAME"
  chmod +x "$installed" 2>/dev/null || true

  desktop_dir="$HOME/.local/share/applications"
  mkdir -p "$desktop_dir"
  icon_path="$install_dir/assets/icon.png"
  {
    echo "[Desktop Entry]"
    echo "Type=Application"
    echo "Name=Generador de clave de TikTok Live (vía Streamlabs)"
    echo "Comment=Prepara una sesión RTMP de TikTok Live a través de Streamlabs"
    echo "Exec=$installed"
    if [ -f "$icon_path" ]; then
      echo "Icon=$icon_path"
    fi
    echo "Terminal=false"
    echo "Categories=AudioVideo;Utility;"
  } > "$desktop_dir/$APP_NAME.desktop"
  command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$desktop_dir" || true
fi

printf '\n'
printf '\033[32m  Instalado correctamente.\033[0m\n'
printf '  Programa: %s\n' "$installed"
[ "$os" = "Linux" ] && printf '  Aparecerá en el menú de aplicaciones.\n'
printf '  Desinstalar: borra %s\n\n' "$installed"
