#!/bin/sh
# Start the app on this computer only. Extra arguments are passed on (--port N, --no-browser, --data FOLDER).
set -eu
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo 'Python 3.11 or newer is needed.' >&2; exit 1; }
exec python3 -m derive.web "$@"
