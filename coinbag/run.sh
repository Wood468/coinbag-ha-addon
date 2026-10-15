#!/bin/sh
LOG_LEVEL=$(python3 -c "import json;print(json.load(open('/data/options.json')).get('log_level','info').upper())" 2>/dev/null || echo INFO)
export LOG_LEVEL
exec python3 -u /app/main.py
