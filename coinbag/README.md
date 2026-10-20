# Coin Bag

Makes your Home Assistant host act as the "Nintendo Switch" for Pokémon GO's postcard exchange, hands-free.
Based on the protocol work in https://github.com/na-ji/pokemon-go-coin-bag (constants are fetched from there when the image builds).

1. Start the add-on. Check the Log tab says "scanning".
2. Pokémon GO: Settings → Connected devices → Nintendo Switch → Connect (phone near the host). Log shows `PAIRED with <name>`.
3. Pokémon GO: Items → Postcard Book → pick a postcard → Send to Nintendo Switch. Log shows `POSTCARD received`.

Entities created: `sensor.coinbag_status`, `sensor.coinbag_postcards` (attributes: last_player, last_at, paired_with).
Use at your own risk: this imitates Nintendo hardware, which may breach Niantic's terms.

# Bedside ESP32-C3 Bluetooth proxy

Coin Bag can use an ESPHome Bluetooth proxy so the ESP32 can sit near the phone while the add-on stays on the Home Assistant host. Keep `transport: bluez` to use a local Bluetooth adapter, or select `transport: esphome` after the proxy is installed.

The example ESPHome configuration is in [`esp32-c3-proxy.example.yaml`](esp32-c3-proxy.example.yaml). Use ESPHome Device Builder 2026.9.1 or newer; the proxy needs active GATT connections and the pairing feature. The example starts a password-protected setup access point so Wi-Fi credentials do not need to be stored in the firmware YAML.

After the ESPHome device joins Wi-Fi, copy its address (IP or `.local` hostname) and the same API encryption key used by its `api.encryption.key` into the Coin Bag add-on options:

```yaml
transport: esphome
esphome_address: 192.168.1.50
esphome_noise_psk: "<same base64 API key as ESPHome>"
```

The add-on setting for the API key is masked. `adapter` applies only to `transport: bluez`. `notify_mode: start` is a BlueZ compatibility option; the ESPHome transport uses the proxy's native GATT subscription path.
