#!/usr/bin/env bash
# Runs the offline test suite: SQL file lint + generator/dashboard unit tests.
# Python 3.9+ standard library only: no database, no pip install, no network.
set -euo pipefail
cd "$(dirname "$0")"
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v "$@"
