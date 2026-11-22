#!/usr/bin/env sh
# Bootstrap Italia and Leaflet into app/static/vendor: served by the page
# itself, no CDN. Run by `make app` and by the Docker build.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
vendor="$here/static/vendor"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$vendor"
fetch() {  # name version
  curl -fsSL "https://registry.npmjs.org/$1/-/$1-$2.tgz" | tar -xz -C "$tmp"
  mv "$tmp/package" "$tmp/$1"
}
[ -f "$vendor/bootstrap-italia/css/bootstrap-italia.min.css" ] || {
  fetch bootstrap-italia 2.18.3
  rm -rf "$vendor/bootstrap-italia" && mkdir -p "$vendor/bootstrap-italia"
  cp -R "$tmp/bootstrap-italia/dist/css" "$tmp/bootstrap-italia/dist/fonts" "$vendor/bootstrap-italia/"
}
[ -f "$vendor/leaflet/leaflet.js" ] || {
  fetch leaflet 1.9.4
  rm -rf "$vendor/leaflet" && cp -R "$tmp/leaflet/dist" "$vendor/leaflet"
}
echo "vendor ready in $vendor"
