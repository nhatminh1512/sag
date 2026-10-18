#!/bin/sh
# sag installer — no git clone required.
#
#   curl -fsSL https://raw.githubusercontent.com/nhatminh1512/sag/main/install.sh | sh
#
# Overrides:
#   SAG_HOME    install directory   (default: ~/.local/share/sag)
#   SAG_BIN     command directory   (default: ~/.local/bin)
#   SAG_BRANCH  branch or tag       (default: main)
#   SAG_PYTHON  interpreter         (default: python3)
#
# Uninstall:
#   curl -fsSL .../install.sh | sh -s -- --uninstall

set -eu

REPO="nhatminh1512/sag"
BRANCH="${SAG_BRANCH:-main}"
SAG_HOME="${SAG_HOME:-$HOME/.local/share/sag}"
BIN_DIR="${SAG_BIN:-$HOME/.local/bin}"
PY="${SAG_PYTHON:-python3}"
TARBALL="https://codeload.github.com/$REPO/tar.gz/refs/heads/$BRANCH"

say() { printf '%s\n' "$*"; }
die() { printf 'sag installer: %s\n' "$*" >&2; exit 1; }

case "$SAG_HOME" in
  "" | "/" | "$HOME") die "refusing to use SAG_HOME=$SAG_HOME" ;;
esac

if [ "${1:-}" = "--uninstall" ]; then
  rm -f "$BIN_DIR/sag"
  rm -rf "$SAG_HOME"
  say "removed $BIN_DIR/sag and $SAG_HOME"
  exit 0
fi

command -v "$PY" >/dev/null 2>&1 || die "$PY not found — install Python 3.10+ first"
"$PY" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' \
  || die "Python 3.10+ is required (found $("$PY" -V 2>&1))"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

say "downloading $REPO@$BRANCH"
if command -v curl >/dev/null 2>&1; then
  curl -fsSL "$TARBALL" -o "$tmp/sag.tar.gz" || die "download failed"
elif command -v wget >/dev/null 2>&1; then
  wget -qO "$tmp/sag.tar.gz" "$TARBALL" || die "download failed"
else
  die "need curl or wget"
fi

tar -xzf "$tmp/sag.tar.gz" -C "$tmp" || die "could not extract the archive"
src="$tmp/sag-$BRANCH"
[ -d "$src" ] || src="$(find "$tmp" -maxdepth 1 -type d -name 'sag-*' | head -n 1)"
[ -d "$src" ] || die "unexpected archive layout"

rm -rf "$SAG_HOME"
mkdir -p "$SAG_HOME" "$BIN_DIR"
cp -a "$src"/. "$SAG_HOME"/
chmod +x "$SAG_HOME/sag.py" "$SAG_HOME/bin/sag.js" 2>/dev/null || true
ln -sf "$SAG_HOME/sag.py" "$BIN_DIR/sag"

say "installed: $SAG_HOME"
say "command:   $BIN_DIR/sag"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) say "note: add $BIN_DIR to PATH (e.g. export PATH=\"$BIN_DIR:\$PATH\")" ;;
esac

if "$BIN_DIR/sag" --help >/dev/null 2>&1; then
  say "ok: $("$BIN_DIR/sag" --help 2>&1 | head -n 1)"
else
  die "installed, but 'sag --help' failed"
fi

say ""
say "next:"
say "  cd <your-repo> && sag setup && sag check"
