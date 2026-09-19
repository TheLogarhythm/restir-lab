#!/usr/bin/env bash
set -euo pipefail

images=false
case "${1:-}" in
  "") ;;
  --images) images=true; shift ;;
  -h|--help) printf 'Usage: bash build.sh [--images]\n'; exit 0 ;;
  *) printf 'Usage: bash build.sh [--images]\n' >&2; exit 2 ;;
esac
if [ "$#" -ne 0 ]; then
  printf 'Usage: bash build.sh [--images]\n' >&2
  exit 2
fi
for tool in node npx; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    printf 'Missing %s. Install Node.js with npm before building slides.\n' "$tool" >&2
    exit 1
  fi
done

script_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../../.." && pwd)"
output_dir="$repo_root/build/slides"
source_file="$script_dir/pitch.md"
mkdir -p "$output_dir"

marp() {
  npx --yes @marp-team/marp-cli@4.5.1 "$source_file" --html "$@"
}

marp --output "$output_dir/pitch.html"
# Use Node for portable base64 encoding (macOS and GNU base64 flags differ).
node - "$script_dir/assets" "$output_dir/pitch.html" <<'NODE'
const fs = require('node:fs');
const path = require('node:path');
const [assetsDir, htmlPath] = process.argv.slice(2);
let html = fs.readFileSync(htmlPath, 'utf8');
for (const name of fs.readdirSync(assetsDir).filter(name => name.endsWith('.png'))) {
  const uri = 'data:image/png;base64,' + fs.readFileSync(path.join(assetsDir, name)).toString('base64');
  html = html.split('src="assets/' + name + '"').join('src="' + uri + '"');
}
fs.writeFileSync(htmlPath, html, 'utf8');
NODE
marp --pdf --pdf-notes --allow-local-files --output "$output_dir/pitch.pdf"
marp --notes --output "$output_dir/pitch-notes.txt"
if [ "$images" = true ]; then
  marp --images png --image-scale 1.5 --allow-local-files --output "$output_dir/pitch.png"
fi
printf 'Slides: %s\n' "$output_dir"
