// Host-side check: prints protocol outputs for fixed inputs so CI can compare them with the Python add-on.
#include <stdio.h>
#include "../src/proto.h"
static void hex(const char *label, const Bytes &b) {
  printf("%s=", label);
  for (unsigned char c : b) printf("%02x", c);
  printf("\n");
}
int main() {
  Bytes c;
  if (!encodeComplete(12345, "abcdef0123456789", c)) return 1;
  hex("complete", c);
  printf("nonce=%s\n", nonceFromTick(0x0123456789abcdefULL).c_str());
  uint8_t rnd[16];
  for (int i = 0; i < 16; i++) rnd[i] = (uint8_t)(i * 7 + 1);
  printf("appid=%s\n", makeAppId(rnd).c_str());
  hex("gatt", appIdGattValue(makeAppId(rnd)));
  return 0;
}
