#!/usr/bin/env bash
# Build JAR for Linux from a clean virtual environment.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

PYTHON="${PYTHON:-python3}"
VENV=".venv-build"

if [ ! -d "$VENV" ]; then
    "$PYTHON" -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"

python -m pip install --upgrade pip
pip install -r requirements-dev.txt

echo "==> running tests"
python -m unittest discover -s tests -t .

echo "==> building CLI binary"
pyinstaller --clean --noconfirm packaging/jar-cli.spec

echo "==> building desktop binary"
pyinstaller --clean --noconfirm packaging/jar-desktop.spec

echo "==> smoke testing CLI binary"
python scripts/smoke_test.py dist/jar

echo "==> packaging release archive"
python scripts/package_release.py --dist dist --output release --platform linux --arch "$(uname -m)"

echo
echo "Done. Archives are in $(pwd)/release"
