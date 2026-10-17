#!/usr/bin/with-contenv sh
LOG_LEVEL=$(python3 -c "import json;print(json.load(open('/data/options.json')).get('log_level','info').upper())" 2>/dev/null || echo INFO)
ADAPTER=$(python3 -c "import json;print(json.load(open('/data/options.json')).get('adapter','auto'))" 2>/dev/null || echo auto)
NOTIFY_MODE=$(python3 -c "import json;print(json.load(open('/data/options.json')).get('notify_mode','auto'))" 2>/dev/null || echo auto)
export LOG_LEVEL ADAPTER NOTIFY_MODE
exec python3 -u /app/main.py
