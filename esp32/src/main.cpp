// Coin Bag for ESP32-C3: acts as the "Nintendo Switch" for Pokémon GO's postcard exchange over BLE
// and reports status to Home Assistant over MQTT (auto-discovered). Port of the Home Assistant add-on.
#include <Arduino.h>
#include <WiFi.h>
#include <WiFiManager.h>
#include <PubSubClient.h>
#include <Preferences.h>
#include <NimBLEDevice.h>
#include "proto.h"

SET_LOOP_TASK_STACK_SIZE(16 * 1024);

#define BOOT_PIN 9
static const uint32_t INDICATION_TIMEOUT = 15000, SUCCESS_DELAY = 60000, PAIRING_DELAY = 3000;
static const uint32_t BACKOFF[] = {3000, 10000, 30000, 60000};

Preferences prefs;
WiFiClient wifi;
PubSubClient mq(wifi);
String devId, tBase, mqHost, mqUser, mqPass;
uint16_t mqPort = 1883;
bool useMqtt = false;
uint32_t postcards = 0;
String lastPlayer;

// ---------- Home Assistant reporting (MQTT discovery) ----------
static void pub(const String &topic, const String &payload, bool retain = true) {
  if (mq.connected()) mq.publish(topic.c_str(), payload.c_str(), retain);
}
static void discover(const char *key, const char *name, const char *icon, bool numeric) {
  String t = "homeassistant/sensor/coinbag_" + devId + "/" + key + "/config";
  String p = "{\"name\":\"" + String(name) + "\",\"unique_id\":\"coinbag_" + devId + "_" + key + "\",\"state_topic\":\"" + tBase +
             "/" + key + "\",\"availability_topic\":\"" + tBase + "/online\",\"icon\":\"" + icon + "\"";
  if (String(key) == "status") p += ",\"json_attributes_topic\":\"" + tBase + "/attr\"";
  if (numeric) p += ",\"state_class\":\"total_increasing\"";
  p += ",\"device\":{\"identifiers\":[\"coinbag_" + devId + "\"],\"name\":\"Coin Bag ESP32\",\"model\":\"ESP32-C3\",\"manufacturer\":\"DIY\"}}";
  pub(t, p);
}
static void mqttEnsure() {
  if (!useMqtt || mq.connected() || WiFi.status() != WL_CONNECTED) return;
  static uint32_t last = 0;
  if (last && millis() - last < 10000) return;
  last = millis();
  String lwt = tBase + "/online";
  bool ok = mqUser.length() ? mq.connect(("coinbag-" + devId).c_str(), mqUser.c_str(), mqPass.c_str(), lwt.c_str(), 0, true, "offline")
                            : mq.connect(("coinbag-" + devId).c_str(), NULL, NULL, lwt.c_str(), 0, true, "offline");
  if (!ok) { Serial.printf("MQTT connect failed rc=%d\n", mq.state()); return; }
  Serial.println("MQTT connected");
  pub(lwt, "online");
  discover("status", "Coin Bag ESP status", "mdi:bluetooth-connect", false);
  discover("postcards", "Coin Bag ESP postcards received", "mdi:postage-stamp", true);
  discover("last_player", "Coin Bag ESP last player", "mdi:account", false);
  pub(tBase + "/postcards", String(postcards));
  if (lastPlayer.length()) pub(tBase + "/last_player", lastPlayer);
}
static void pump() { mqttEnsure(); if (mq.connected()) mq.loop(); }

static void report(const char *status, const String &detail = "", int heard = -1) {
  Serial.printf("[status] %s %s\n", status, detail.c_str());
  String attr = "{\"detail\":\"" + detail + "\"";
  if (heard >= 0) attr += ",\"ble_devices_heard\":" + String(heard);
  attr += ",\"uptime_s\":" + String(millis() / 1000) + ",\"wifi_rssi\":" + String(WiFi.RSSI()) + "}";
  pub(tBase + "/status", status);
  pub(tBase + "/attr", attr);
  pump();
}

// ---------- BLE ----------
struct Msg { bool stage; Bytes data; };
static QueueHandle_t q;
static String lastErr;

static void onIndication(NimBLERemoteCharacteristic *c, uint8_t *d, size_t n, bool) {
  Msg *m = new Msg{c->getUUID() == NimBLEUUID(UUID_STAGE), Bytes((const char *)d, n)};
  if (xQueueSend(q, &m, 0) != pdTRUE) delete m;
}
static Msg *waitMsg(uint32_t ms) {
  uint32_t t0 = millis();
  Msg *m = nullptr;
  while (millis() - t0 < ms) {
    if (xQueueReceive(q, &m, pdMS_TO_TICKS(100)) == pdTRUE) return m;
    pump();
  }
  return nullptr;
}
static void drain() { Msg *m; while (xQueueReceive(q, &m, 0) == pdTRUE) delete m; }

static NimBLERemoteCharacteristic *findChar(NimBLEClient *c, const char *uuid) {
  NimBLERemoteService *s = c->getService(UUID_GATT);
  return s ? s->getCharacteristic(uuid) : nullptr;
}
static bool rd(NimBLEClient *c, const char *uuid, Bytes &out) {
  auto ch = findChar(c, uuid);
  if (!ch) { lastErr = String("missing characteristic ") + uuid; return false; }
  out = ch->readValue();
  return true;
}
static bool wr(NimBLEClient *c, const char *uuid, const Bytes &v, bool resp) {
  auto ch = findChar(c, uuid);
  if (!ch) { lastErr = String("missing characteristic ") + uuid; return false; }
  if (!ch->writeValue((const uint8_t *)v.data(), v.size(), resp)) { lastErr = String("write failed ") + uuid; return false; }
  return true;
}

enum Result { R_FAIL, R_PAIRED, R_RECEIVED, R_UNCONFIRMED };
#define FAIL(msg) do { lastErr = (msg); return R_FAIL; } while (0)

static Result exchange(NimBLEClient *cl, const std::string &appId, const std::string &nonce) {
  auto finalChar = findChar(cl, UUID_FINALNONCE), dataChar = findChar(cl, UUID_DATA), stageChar = findChar(cl, UUID_STAGE);
  if (!finalChar || !dataChar || !stageChar) FAIL("exchange characteristics missing");
  drain();
  Serial.println("step: write application ID");
  if (!wr(cl, UUID_APPID, appIdGattValue(appId), true)) return R_FAIL;
  Serial.println("step: write initial nonce");
  if (!wr(cl, UUID_INITNONCE, Bytes(nonce + '\0'), false)) return R_FAIL;
  Serial.println("step: subscribe DATA");
  if (!dataChar->subscribe(false, onIndication, true)) FAIL("subscribe DATA failed");

  Msg *m = waitMsg(INDICATION_TIMEOUT);
  if (!m) FAIL("no first indication");
  Serial.printf("first indication %u bytes (MTU %u)\n", (unsigned)m->data.size(), cl->getMTU());
  if (m->data.size() < 303) { delete m; FAIL("first indication too short; ATT MTU " + String(cl->getMTU())); }
  BleSend send;
  bool ok = decodeSend(m->data, send);
  delete m;
  if (!ok) FAIL("could not decode first indication");
  if (send.appId != appId) FAIL("server response application ID mismatch");
  if (send.nonce != nonce) FAIL("server response nonce mismatch");
  Bytes complete;
  if (!encodeComplete(send.txid, send.nonce, complete)) FAIL("signing failed");

  Serial.println("step: subscribe STAGE");
  if (!stageChar->subscribe(false, onIndication, true)) FAIL("subscribe STAGE failed");
  Serial.println("step: write completion");
  if (!wr(cl, UUID_COMPLETE, complete, false)) return R_FAIL;

  m = waitMsg(INDICATION_TIMEOUT);  // iOS sends finalize on STAGE, Android on DATA
  if (!m) { lastErr = "finalize timed out"; return R_UNCONFIRMED; }
  BleFinalize fin;
  ok = decodeFinalize(m->data, fin);
  delete m;
  if (!ok) FAIL("could not decode finalize");
  if (fin.appId != appId) FAIL("finalize application ID mismatch");
  if (fin.nonce != nonce) FAIL("finalize nonce mismatch");
  Serial.println("step: write final nonce");
  if (!finalChar->writeValue((const uint8_t *)nonce.data(), nonce.size(), true)) Serial.println("final nonce write failed (GO may have closed GATT)");
  return R_RECEIVED;
}

static std::string appId;

static Result handle(NimBLEClient *cl, String &playerName) {
  Bytes v;
  if (!rd(cl, UUID_PROTOCOL, v)) return R_FAIL;
  if (v.size() != 1 || v[0] != 1) FAIL("unsupported protocol value");
  if (!rd(cl, UUID_NAME, v)) return R_FAIL;
  if (v.size() < 4 || v.size() > 15) FAIL("bad player name");
  playerName = String(v.c_str());
  Bytes mode;
  if (!rd(cl, UUID_MODE, mode)) return R_FAIL;
  if (mode.size() != 1) FAIL("invalid mode characteristic");
  if (appId.empty()) {
    uint8_t rnd[16];
    esp_fill_random(rnd, 16);
    appId = makeAppId(rnd);
    prefs.putString("appid", appId.c_str());
  }
  uint64_t tick = ((uint64_t)esp_random() << 32) | esp_random();
  std::string nonce = nonceFromTick(tick);
  if (mode[0] == 0x00) {
    report("pairing", playerName);
    delay(250);
    if (!wr(cl, UUID_APPID, appIdGattValue(appId), true)) return R_FAIL;
    Serial.println("PAIRED with " + playerName);
    return R_PAIRED;
  }
  if (mode[0] == 0x01) {
    report("exchanging", playerName);
    return exchange(cl, appId, nonce);
  }
  FAIL("unsupported mode");
}

static NimBLEAddress foundAddr;
static bool scanForPhone() {
  NimBLEScan *sc = NimBLEDevice::getScan();
  sc->setActiveScan(true);
  sc->setInterval(100);
  sc->setWindow(99);
  NimBLEScanResults r = sc->start(5, false);
  int heard = r.getCount();
  bool found = false;
  for (int i = 0; i < heard && !found; i++) {
    NimBLEAdvertisedDevice *d = r.getDevice(i);
    if (d->isAdvertisingService(NimBLEUUID(UUID_ADV))) { foundAddr = d->getAddress(); found = true; }
  }
  sc->clearResults();
  if (!found) report("scanning", "", heard);
  return found;
}

static Result connectAndHandle(String &playerName) {
  NimBLEClient *cl = NimBLEDevice::createClient();
  cl->setConnectTimeout(30);
  Result res = R_FAIL;
  if (!cl->connect(foundAddr)) {
    lastErr = "connect failed";
  } else {
    Serial.printf("connected, MTU %u\n", cl->getMTU());
    if (!cl->secureConnection()) Serial.println("secureConnection failed/declined; continuing");
    delay(75);
    res = handle(cl, playerName);
  }
  if (cl->isConnected()) cl->disconnect();
  NimBLEDevice::deleteClient(cl);
  return res;
}

// ---------- setup / loop ----------
static void saveParams(WiFiManagerParameter *h, WiFiManagerParameter *p, WiFiManagerParameter *u, WiFiManagerParameter *w) {
  prefs.putString("mqhost", h->getValue());
  prefs.putUShort("mqport", (uint16_t)atoi(p->getValue()));
  prefs.putString("mquser", u->getValue());
  prefs.putString("mqpass", w->getValue());
}

void setup() {
  Serial.begin(115200);
  delay(500);
  pinMode(BOOT_PIN, INPUT_PULLUP);
  prefs.begin("coinbag", false);
  q = xQueueCreate(8, sizeof(Msg *));
  uint8_t mac[6];
  WiFi.macAddress(mac);
  char id[8];
  snprintf(id, sizeof id, "%02x%02x%02x", mac[3], mac[4], mac[5]);
  devId = id;
  tBase = "coinbag/" + devId;
  appId = prefs.getString("appid", "").c_str();
  postcards = prefs.getUInt("cards", 0);
  lastPlayer = prefs.getString("last", "");
  mqHost = prefs.getString("mqhost", "");
  mqPort = prefs.getUShort("mqport", 1883);
  mqUser = prefs.getString("mquser", "");
  mqPass = prefs.getString("mqpass", "");

  bool reset = false;
  if (digitalRead(BOOT_PIN) == LOW) {  // hold BOOT while powering up for 3 s: forget Wi-Fi/MQTT settings and Bluetooth bonds
    delay(3000);
    reset = digitalRead(BOOT_PIN) == LOW;
  }

  WiFiManager wm;
  char portBuf[8];
  snprintf(portBuf, sizeof portBuf, "%u", mqPort);
  WiFiManagerParameter pHost("host", "Home Assistant MQTT broker (IP or host)", mqHost.c_str(), 64);
  WiFiManagerParameter pPort("port", "MQTT port", portBuf, 6);
  WiFiManagerParameter pUser("user", "MQTT username", mqUser.c_str(), 64);
  WiFiManagerParameter pPass("pass", "MQTT password", mqPass.c_str(), 64, "type=\"password\"");
  wm.addParameter(&pHost); wm.addParameter(&pPort); wm.addParameter(&pUser); wm.addParameter(&pPass);
  wm.setConfigPortalTimeout(300);
  wm.setBreakAfterConfig(true);
  if (reset) { wm.resetSettings(); prefs.clear(); appId.clear(); Serial.println("settings reset"); }
  Serial.println("Wi-Fi: connecting (setup network is CoinBag-Setup if no saved Wi-Fi)");
  bool ok = wm.autoConnect("CoinBag-Setup");
  if (ok) {
    saveParams(&pHost, &pPort, &pUser, &pPass);
    mqHost = pHost.getValue(); mqPort = (uint16_t)atoi(pPort.getValue()); mqUser = pUser.getValue(); mqPass = pPass.getValue();
    if (!mqPort) mqPort = 1883;
  }
  useMqtt = ok && mqHost.length();
  if (useMqtt) { mq.setServer(mqHost.c_str(), mqPort); mq.setBufferSize(1024); }
  Serial.printf("Wi-Fi %s, MQTT %s\n", ok ? "up" : "not connected (BLE still runs)", useMqtt ? "enabled" : "off");

  NimBLEDevice::init("CoinBag");
  NimBLEDevice::setMTU(517);
  NimBLEDevice::setSecurityAuth(true, false, true);
  NimBLEDevice::setSecurityIOCap(BLE_HS_IO_NO_INPUT_OUTPUT);
  if (reset) NimBLEDevice::deleteAllBonds();
  report("scanning");
}

void loop() {
  static int fails = 0;
  pump();
  if (WiFi.status() != WL_CONNECTED && useMqtt) { static uint32_t t = 0; if (millis() - t > 15000) { t = millis(); WiFi.reconnect(); } }
  if (!scanForPhone()) return;
  Serial.println("Pokémon GO found: " + String(foundAddr.toString().c_str()));
  report("connecting");
  String name;
  Result r = connectAndHandle(name);
  if (r == R_FAIL) {
    report("failed", lastErr);
    uint32_t w = BACKOFF[min(fails, 3)];
    fails++;
    Serial.printf("waiting %u ms (%d failures)\n", (unsigned)w, fails);
    uint32_t t0 = millis();
    while (millis() - t0 < w) { pump(); delay(50); }
    return;
  }
  fails = 0;
  if (r == R_RECEIVED) {
    postcards++;
    lastPlayer = name;
    prefs.putUInt("cards", postcards);
    prefs.putString("last", name);
    pub(tBase + "/postcards", String(postcards));
    pub(tBase + "/last_player", name);
    report("received", name);
  } else {
    report(r == R_PAIRED ? "paired" : "unconfirmed", r == R_PAIRED ? name : lastErr);
  }
  uint32_t d = r == R_PAIRED ? PAIRING_DELAY : SUCCESS_DELAY;
  uint32_t t0 = millis();
  while (millis() - t0 < d) { pump(); delay(50); }
}
