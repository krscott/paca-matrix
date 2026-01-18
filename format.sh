#!/usr/bin/env sh
set -eu

isort .
black .

if command -v nix >/dev/null; then
    for file in $(git ls-files '*.nix'); do
        nix fmt "$file"
    done
fi
