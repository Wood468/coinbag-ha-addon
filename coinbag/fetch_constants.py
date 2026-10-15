"""Download the upstream protocol constants (UUIDs, signing material) at image build time and decode them.
They are not redistributed in this repository."""
import base64, json, re, sys, urllib.request
REV = "368a1f40008855a2f294a5de2b193828bde4d1b6"  # na-ji/pokemon-go-coin-bag, pinned
URL = f"https://raw.githubusercontent.com/na-ji/pokemon-go-coin-bag/{REV}/docs/protocol.js"
src = sys.argv[2] if len(sys.argv) > 2 else None
text = open(src).read() if src else urllib.request.urlopen(URL, timeout=30).read().decode()
blob = "".join(re.search(r"const CONSTANTS = `(.*?)`;", text, re.S).group(1).split())
json.dump(json.loads(base64.b64decode(blob)), open(sys.argv[1], "w"))
print("constants written")
