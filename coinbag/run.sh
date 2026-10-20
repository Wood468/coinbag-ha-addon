#!/usr/bin/with-contenv sh
LOG_LEVEL=$(python3 -c "import json;print(json.load(open('/data/options.json')).get('log_level','info').upper())" 2>/dev/null || echo INFO)
ADAPTER=$(python3 -c "import json;print(json.load(open('/data/options.json')).get('adapter','auto'))" 2>/dev/null || echo auto)
NOTIFY_MODE=$(python3 -c "import json;print(json.load(open('/data/options.json')).get('notify_mode','auto'))" 2>/dev/null || echo auto)
TRANSPORT=$(python3 -c "import json;print(json.load(open('/data/options.json')).get('transport','bluez'))" 2>/dev/null || echo bluez)
ESPHOME_ADDRESS=$(python3 -c "import json;print(json.load(open('/data/options.json')).get('esphome_address',''))" 2>/dev/null || echo '')
ESPHOME_NOISE_PSK=$(python3 -c "import json;print(json.load(open('/data/options.json')).get('esphome_noise_psk',''))" 2>/dev/null || echo '')
export LOG_LEVEL ADAPTER NOTIFY_MODE TRANSPORT ESPHOME_ADDRESS ESPHOME_NOISE_PSK
exec python3 -u /app/main.py
