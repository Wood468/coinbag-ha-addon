# Coin Bag on ESP32-C3

Runs the same Pokémon GO postcard exchange as the add-on, but on a $5 ESP32-C3 board placed wherever Bluetooth reaches your phone (e.g. by the bed). Status reaches Home Assistant over Wi-Fi via MQTT (auto-discovered sensors: status, postcards received, last player).

## Flash (once, from a computer with Chrome/Edge)
1. Download `coinbag-esp32c3.bin` from this repo's **Releases → esp32-latest** (or the latest Actions run's artifact).
2. Plug the board in by USB, open https://web.esphome.io, click **Connect**, pick the board, then **Install** → choose the file.
3. Unplug and power it from any USB charger.

## First-time setup
1. The board makes a Wi-Fi network called **CoinBag-Setup**. Join it on your phone; a page opens (or go to 192.168.4.1).
2. Pick your home Wi-Fi and enter its password, plus your Home Assistant MQTT broker (Mosquitto add-on: HA's IP, port 1883, a user/password you created for it).
3. In Home Assistant the **Coin Bag ESP** device appears under MQTT. Pair it in Pokémon GO as before.

To change Wi-Fi/MQTT or clear Bluetooth bonds: hold the BOOT button while plugging in, for 3 seconds.
Don't run this and the add-on at the same time (both would answer the phone).

Constants (UUIDs, signing material) are downloaded at build time, never stored in the repo.
