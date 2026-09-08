#!/usr/bin/env bash
set -euo pipefail

APP_ID="io.github.xarishark.mount-manager"
APPIMAGE_NAME="SMB-Mount-Manager"
SUPPORTED_ARCH="x86_64"

usage() {
  cat <<EOF
Usage: ${0##*/} [--appdir-only] [VERSION]

Build a Bazzite-focused AppImage for SMB Mount Manager.

Options:
  --appdir-only  Prepare the AppDir without running appimagetool.
  -h, --help     Show this help.

Environment:
  ARCH                 Target architecture. Only x86_64 is supported.
  APPIMAGETOOL         Path to an existing appimagetool executable.
  APPIMAGETOOL_URL     Download URL used when APPIMAGETOOL is not set.
  BUILD_DIR            Build directory. Defaults to build/appimage.
  DIST_DIR             Output directory. Defaults to dist.
EOF
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
arch="${ARCH:-$SUPPORTED_ARCH}"
version="${VERSION:-}"
appdir_only=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --appdir-only)
      appdir_only=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    -*)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
    *)
      if [ -n "$version" ]; then
        echo "Version was provided more than once." >&2
        exit 2
      fi
      version="$1"
      ;;
  esac
  shift
done

if [ "$arch" != "$SUPPORTED_ARCH" ]; then
  echo "Unsupported ARCH=$arch. This AppImage flow currently supports x86_64 only." >&2
  exit 2
fi

if [ -z "$version" ]; then
  version="$(
    sed -n -E \
      's/^[[:space:]]*<release[^>]*version="?([^"]+)"?.*/\1/p; s/^[[:space:]]*<component[^>]*version="?([^"]+)"?.*/\1/p' \
      "$repo_root/data/metainfo/$APP_ID.metainfo.xml" |
      head -n1
  )"
fi

if [ -z "$version" ]; then
  echo "No version found. Pass VERSION or add one to data/metainfo/$APP_ID.metainfo.xml." >&2
  exit 1
fi

build_dir="${BUILD_DIR:-$repo_root/build/appimage}"
dist_dir="${DIST_DIR:-$repo_root/dist}"
appdir="$build_dir/$APP_ID.AppDir"
output="$dist_dir/$APPIMAGE_NAME-$version-$arch.AppImage"

rm -rf "$appdir"
mkdir -p "$appdir/usr/bin"
mkdir -p "$appdir/usr/share/applications"
mkdir -p "$appdir/usr/share/doc/$APP_ID"
mkdir -p "$appdir/usr/share/icons/hicolor/scalable/apps"
mkdir -p "$appdir/usr/share/licenses/$APP_ID"
mkdir -p "$appdir/usr/share/metainfo"
mkdir -p "$dist_dir"

install -D -m 0755 "$repo_root/mount_manager.py" "$appdir/usr/bin/mount_manager.py"
install -D -m 0644 "$repo_root/mount_manager_ui.py" "$appdir/usr/bin/mount_manager_ui.py"
if ! command -v git >/dev/null 2>&1; then
  echo "git is required to apply the AppImage helper workaround." >&2
  exit 1
fi
(
  cd "$appdir/usr/bin"
  GIT_DIR= GIT_WORK_TREE=. git apply --no-index --quiet "$repo_root/packaging/appimage-helper.patch"
)
ln -sf mount_manager.py "$appdir/usr/bin/mount-manager"
install -D -m 0644 "$repo_root/data/icons/hicolor/scalable/apps/$APP_ID.svg" \
  "$appdir/usr/share/icons/hicolor/scalable/apps/$APP_ID.svg"
install -D -m 0644 "$repo_root/data/metainfo/$APP_ID.metainfo.xml" \
  "$appdir/usr/share/metainfo/$APP_ID.metainfo.xml"
install -D -m 0644 "$repo_root/README.md" "$appdir/usr/share/doc/$APP_ID/README.md"
install -D -m 0644 "$repo_root/LICENSE" "$appdir/usr/share/licenses/$APP_ID/LICENSE"

desktop_file="$appdir/usr/share/applications/$APP_ID.desktop"
while IFS= read -r line; do
  printf '%s\n' "$line"
  if [ "$line" = "[Desktop Entry]" ]; then
    printf 'X-AppImage-Version=%s\n' "$version"
  fi
done <"$repo_root/data/applications/$APP_ID.desktop" >"$desktop_file"

cat >"$appdir/AppRun" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

appdir="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
export APPDIR="${APPDIR:-$appdir}"
export PATH="$appdir/usr/bin:$PATH"

default_xdg_data_dirs="/usr/local/share:/usr/share"
export XDG_DATA_DIRS="$appdir/usr/share:${XDG_DATA_DIRS:-$default_xdg_data_dirs}"

exec "$appdir/usr/bin/mount-manager" "$@"
EOF
chmod 0755 "$appdir/AppRun"

ln -s "usr/share/applications/$APP_ID.desktop" "$appdir/$APP_ID.desktop"
ln -s "usr/share/icons/hicolor/scalable/apps/$APP_ID.svg" "$appdir/$APP_ID.svg"
ln -s "$APP_ID.svg" "$appdir/.DirIcon"

if command -v desktop-file-validate >/dev/null 2>&1; then
  desktop-file-validate "$desktop_file"
fi

if command -v appstreamcli >/dev/null 2>&1; then
  appstreamcli validate --no-net "$appdir/usr/share/metainfo/$APP_ID.metainfo.xml"
fi

if [ "$appdir_only" -eq 1 ]; then
  echo "Prepared AppDir: $appdir"
  exit 0
fi

appimagetool="${APPIMAGETOOL:-}"
if [ -z "$appimagetool" ] && command -v appimagetool >/dev/null 2>&1; then
  appimagetool="$(command -v appimagetool)"
fi

if [ -z "$appimagetool" ]; then
  appimagetool="$build_dir/appimagetool-$arch.AppImage"
  if [ ! -x "$appimagetool" ]; then
    appimagetool_url="${APPIMAGETOOL_URL:-https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-$arch.AppImage}"
    echo "Downloading appimagetool from $appimagetool_url"
    curl -fsSL "$appimagetool_url" -o "$appimagetool"
    chmod 0755 "$appimagetool"
  fi
fi

if [ ! -x "$appimagetool" ]; then
  echo "appimagetool is not executable: $appimagetool" >&2
  exit 1
fi

echo "Using appimagetool: $appimagetool"
"$appimagetool" --version || true

rm -f "$output" "$output.sha256" "$output.zsync"
UPDATE_INFO="zsync|https://github.com/Xarishark/mount-manager/releases/download/v${version}/${APPIMAGE_NAME}-${version}-${arch}.AppImage.zsync"
echo "Building AppImage with UPDATE_INFO: $UPDATE_INFO"
if ! ARCH="$arch" APPIMAGE_EXTRACT_AND_RUN=1 "$appimagetool" -u "$UPDATE_INFO" "$appdir" "$output"; then
  echo "appimagetool failed to build AppImage" >&2
  exit 1
fi
chmod 0755 "$output"

# Verify zsync file was created by appimagetool
if [ ! -f "$output.zsync" ]; then
  echo "WARNING: zsync file not created by appimagetool, generating with zsyncmake..." >&2
  if ! command -v zsyncmake >/dev/null 2>&1; then
    echo "ERROR: zsyncmake not found. Install zsync package." >&2
    exit 1
  fi
  zsyncmake -e "$output" -o "$output.zsync"
fi

# List files in dist directory for debugging
echo "Files in dist directory:"
ls -lh "$dist_dir/" || true

# Final verification
if [ ! -f "$output.zsync" ]; then
  echo "ERROR: zsync file was not created: $output.zsync" >&2
  echo "This is required for delta updates." >&2
  echo "The UPDATE_INFO used was: $UPDATE_INFO" >&2
  exit 1
fi

(
  cd "$dist_dir"
  sha256sum "${output##*/}" >"${output##*/}.sha256"
)

echo "Built AppImage: $output"
echo "Built checksum: $output.sha256"
echo "Built zsync: $output.zsync"
