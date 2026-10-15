# Coin Bag

Makes your Home Assistant host act as the "Nintendo Switch" for Pokémon GO's postcard exchange, hands-free.
Based on the protocol work in https://github.com/na-ji/pokemon-go-coin-bag (constants are fetched from there when the image builds).

1. Start the add-on. Check the Log tab says "scanning".
2. Pokémon GO: Settings → Connected devices → Nintendo Switch → Connect (phone near the host). Log shows `PAIRED with <name>`.
3. Pokémon GO: Items → Postcard Book → pick a postcard → Send to Nintendo Switch. Log shows `POSTCARD received`.

Entities created: `sensor.coinbag_status`, `sensor.coinbag_postcards` (attributes: last_player, last_at, paired_with).
Use at your own risk: this imitates Nintendo hardware, which may breach Niantic's terms.
