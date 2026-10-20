// Pokémon GO postcard protocol helpers: hand-rolled protobuf, RSA signature, nonce and ids.
// No Arduino dependencies so it can be unit-tested on a normal computer.
#pragma once
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include <string>
#include <mbedtls/bignum.h>
#include <mbedtls/sha1.h>
#include <mbedtls/sha256.h>
#include <mbedtls/version.h>
#include "constants.h"

typedef std::string Bytes;

static inline void sha256(const void *in, size_t n, uint8_t out[32]) {
#if MBEDTLS_VERSION_MAJOR >= 3
  mbedtls_sha256((const unsigned char *)in, n, out, 0);
#else
  mbedtls_sha256_ret((const unsigned char *)in, n, out, 0);
#endif
}
static inline void sha1(const void *in, size_t n, uint8_t out[20]) {
#if MBEDTLS_VERSION_MAJOR >= 3
  mbedtls_sha1((const unsigned char *)in, n, out);
#else
  mbedtls_sha1_ret((const unsigned char *)in, n, out);
#endif
}

// ---- protobuf (varint + length-delimited only) ----
static inline void putVarint(Bytes &o, uint64_t v) {
  while (v > 0x7f) { o.push_back((char)((v & 0x7f) | 0x80)); v >>= 7; }
  o.push_back((char)v);
}
static inline void putBytes(Bytes &o, int field, const Bytes &v) {
  putVarint(o, ((uint64_t)field << 3) | 2);
  putVarint(o, v.size());
  o += v;
}
static inline void putVarintField(Bytes &o, int field, uint64_t v) {
  putVarint(o, (uint64_t)field << 3);
  putVarint(o, v);
}

struct Field { int wire = -1; uint64_t num = 0; Bytes bytes; };
#define MAXF 9

static inline bool readVarint(const Bytes &d, size_t &off, uint64_t &v) {
  v = 0;
  for (int shift = 0; off < d.size() && shift < 70; shift += 7) {
    uint8_t b = (uint8_t)d[off++];
    v |= (uint64_t)(b & 0x7f) << shift;
    if (!(b & 0x80)) return true;
  }
  return false;
}
// Fills f[1..MAXF-1] by field number; ignores higher numbers.
static inline bool parseFields(const Bytes &d, Field f[MAXF]) {
  size_t off = 0;
  while (off < d.size()) {
    uint64_t tag;
    if (!readVarint(d, off, tag)) return false;
    uint64_t n = tag >> 3, wire = tag & 7;
    if (n == 0) return false;
    Field fld;
    fld.wire = (int)wire;
    if (wire == 0) {
      if (!readVarint(d, off, fld.num)) return false;
    } else if (wire == 2) {
      uint64_t len;
      if (!readVarint(d, off, len) || len > d.size() - off) return false;
      fld.bytes = d.substr(off, (size_t)len);
      off += (size_t)len;
    } else return false;
    if (n < MAXF) f[n] = fld;
  }
  return true;
}

struct BleSend { uint64_t txid; std::string appId, nonce; };
static inline bool decodeSend(const Bytes &data, BleSend &out) {
  Field o[MAXF], p[MAXF];
  if (!parseFields(data, o) || o[1].wire != 2 || !parseFields(o[1].bytes, p)) return false;
  if (p[2].wire != 0 || p[3].wire != 2 || p[4].wire != 2) return false;
  out.txid = p[2].num; out.appId = p[3].bytes; out.nonce = p[4].bytes;
  return true;
}
struct BleFinalize { std::string nonce, appId; };
static inline bool decodeFinalize(const Bytes &data, BleFinalize &out) {
  Field o[MAXF], p[MAXF];
  if (!parseFields(data, o) || o[1].wire != 2 || !parseFields(o[1].bytes, p)) return false;
  if (p[1].wire != 2 || p[2].wire != 2) return false;
  out.nonce = p[1].bytes; out.appId = p[2].bytes;
  return true;
}

// ---- RSA PKCS#1 v1.5 / SHA-256 using the upstream private key ----
static inline Bytes fromHex(const char *h) {
  Bytes o;
  for (size_t i = 0; h[i] && h[i + 1]; i += 2) { unsigned v; sscanf(h + i, "%2x", &v); o.push_back((char)v); }
  return o;
}
static inline bool rsaSign(const Bytes &msg, uint8_t out[256]) {
  uint8_t digest[32];
  sha256(msg.data(), msg.size(), digest);
  Bytes prefix = fromHex(DIGEST_PREFIX_HEX);
  int pad = 256 - 3 - (int)prefix.size() - 32;
  if (pad < 8) return false;
  uint8_t em[256];
  size_t p = 0;
  em[p++] = 0; em[p++] = 1;
  memset(em + p, 0xff, pad); p += pad;
  em[p++] = 0;
  memcpy(em + p, prefix.data(), prefix.size()); p += prefix.size();
  memcpy(em + p, digest, 32);
  mbedtls_mpi N, D, X, R;
  mbedtls_mpi_init(&N); mbedtls_mpi_init(&D); mbedtls_mpi_init(&X); mbedtls_mpi_init(&R);
  bool ok = mbedtls_mpi_read_string(&N, 16, RSA_N_HEX) == 0 && mbedtls_mpi_read_string(&D, 16, RSA_D_HEX) == 0 &&
            mbedtls_mpi_read_binary(&X, em, 256) == 0 && mbedtls_mpi_exp_mod(&R, &X, &D, &N, NULL) == 0 &&
            mbedtls_mpi_write_binary(&R, out, 256) == 0;
  mbedtls_mpi_free(&N); mbedtls_mpi_free(&D); mbedtls_mpi_free(&X); mbedtls_mpi_free(&R);
  return ok;
}
static inline bool encodeComplete(uint64_t txid, const std::string &nonce, Bytes &out) {
  Bytes share;
  putVarintField(share, 1, txid);
  putBytes(share, 2, nonce);
  uint8_t sig[256];
  if (!rsaSign(share, sig)) return false;
  out.clear();
  putBytes(out, 1, share);
  putBytes(out, 2, Bytes((const char *)sig, 256));
  putBytes(out, 3, Bytes((const char *)sig, 16));
  return true;
}

// ---- ids, nonces, GATT values ----
static inline std::string nonceFromTick(uint64_t tick) {
  uint64_t v = 0xcbf29ce484222645ULL;
  for (int i = 0; i < 8; i++) { v ^= (tick >> (8 * i)) & 0xff; v *= 0x100000001b3ULL; }
  char b[24];
  snprintf(b, sizeof b, "%llx", (unsigned long long)v);
  return b;
}
static inline std::string makeAppId(const uint8_t rnd[16]) {
  static const uint8_t ns[16] = {0x6b,0xa7,0xb8,0x10,0x9d,0xad,0x11,0xd1,0x80,0xb4,0x00,0xc0,0x4f,0xd4,0x30,0xc8};
  uint8_t buf[32], h[20];
  memcpy(buf, ns, 16); memcpy(buf + 16, rnd, 16);
  sha1(buf, 32, h);
  h[6] = (h[6] & 0x0f) | 0x50;
  h[8] = (h[8] & 0x3f) | 0x80;
  char s[40];
  snprintf(s, sizeof s, "%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x",
           h[0],h[1],h[2],h[3],h[4],h[5],h[6],h[7],h[8],h[9],h[10],h[11],h[12],h[13],h[14],h[15]);
  return std::string(s) + APP_ID_SUFFIX;
}
static inline Bytes appIdGattValue(const std::string &id) {
  Bytes v = id;
  v.resize(APP_ID_WIDTH, '\0');
  return v;
}
