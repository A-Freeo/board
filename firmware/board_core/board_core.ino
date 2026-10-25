/*
  Board firmware v3.1: a Bluetooth keyboard you wear on one hand
  Touch a fingertip to your thumb and the board types a key on the paired computer:
    index tip   = next page (Page Down)
    index lower = previous page (Page Up), the pad lower down the index finger
    ring        = ask Oswald (F18)
  Hold either index pad to keep turning pages. Two pads at once do nothing. The hub on the laptop listens for F18.
  Pair "Board" in the computer's Bluetooth settings.

  Power: the breadboard power module (set to 5V) feeds the ESP32's 5V pin.
  Arduino IDE: Tools > Board > ESP32 Dev Module, then Upload. The default settings are fine.
*/

#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEHIDDevice.h>
#include <BLESecurity.h>

#define DEVICE_NAME "Board"

// ---------- What each finger does (a hold repeats while the finger stays down) ----------
enum Key { NEXT_PAGE, PREVIOUS_PAGE, OSWALD };

struct Control {
  const char* trigger;
  Key key;
  bool repeats;
};

Control CONTROLS[] = {
  {"index tip",         NEXT_PAGE,     false},
  {"index tip hold",    NEXT_PAGE,     true},
  {"index lower",       PREVIOUS_PAGE, false},
  {"index lower hold",  PREVIOUS_PAGE, true},
  {"ring",              OSWALD,        false},
  {"ring hold",         OSWALD,        false},
};

// ---------- Settings ----------
const uint32_t DEBOUNCE_MS = 30;
const uint32_t HOLD_MS     = 600;   // a touch this long is a hold
const uint32_t REPEAT_MS   = 250;   // how fast holds repeat

// ---------- Types (keep above every function) ----------
struct Pad {
  const char* name;
  int pin;
  bool raw;
  bool down;
  uint32_t changedAt;
};

// ---------- What the board knows ----------
Pad pads[] = {
  {"index tip",   13},
  {"index lower", 14},
  {"ring",        27},
};
const int PAD_COUNT = 3;
uint8_t fingersDown = 0;          // one bit per finger

bool computerConnected = false;   // a computer is paired over Bluetooth

void noteGesture(const char* text) {
  Serial.println(text);
}

// =====================================================================
// Bluetooth keyboard for the paired computer
// (the report map also has media keys and a mouse, so a computer that paired before keeps working)
// =====================================================================
const uint8_t HID_MAP[] = {
  0x05, 0x01, 0x09, 0x06, 0xA1, 0x01, 0x85, 0x01,             // keyboard, report 1
  0x05, 0x07, 0x19, 0xE0, 0x29, 0xE7, 0x15, 0x00, 0x25, 0x01,
  0x75, 0x01, 0x95, 0x08, 0x81, 0x02, 0x95, 0x01, 0x75, 0x08, 0x81, 0x01,
  0x95, 0x06, 0x75, 0x08, 0x15, 0x00, 0x25, 0x73, 0x05, 0x07, 0x19, 0x00, 0x29, 0x73, 0x81, 0x00,
  0xC0,
  0x05, 0x0C, 0x09, 0x01, 0xA1, 0x01, 0x85, 0x02,             // media keys, report 2
  0x15, 0x00, 0x26, 0xFF, 0x03, 0x19, 0x00, 0x2A, 0xFF, 0x03, 0x75, 0x10, 0x95, 0x01, 0x81, 0x00,
  0xC0,
  0x05, 0x01, 0x09, 0x02, 0xA1, 0x01, 0x85, 0x03, 0x09, 0x01, 0xA1, 0x00,   // mouse, report 3
  0x05, 0x09, 0x19, 0x01, 0x29, 0x03, 0x15, 0x00, 0x25, 0x01, 0x95, 0x03, 0x75, 0x01, 0x81, 0x02,
  0x95, 0x01, 0x75, 0x05, 0x81, 0x03,
  0x05, 0x01, 0x09, 0x30, 0x09, 0x31, 0x09, 0x38, 0x15, 0x81, 0x25, 0x7F, 0x75, 0x08, 0x95, 0x03, 0x81, 0x06,
  0xC0, 0xC0
};

const uint8_t KEY_PAGE_DOWN = 0x4E, KEY_PAGE_UP = 0x4B, KEY_F18 = 0x6D;

BLEHIDDevice* hid;
BLECharacteristic* keyboardReport;

class ComputerEvents : public BLEServerCallbacks {
  void onConnect(BLEServer* s) override { computerConnected = true; }
  void onDisconnect(BLEServer* s) override { computerConnected = false; }
};

void setupBluetooth() {
  BLEDevice::init(DEVICE_NAME);
  BLESecurity* security = new BLESecurity();
  security->setCapability(ESP_IO_CAP_NONE);
  security->setAuthenticationMode(true, false, true);

  BLEServer* server = BLEDevice::createServer();
  server->setCallbacks(new ComputerEvents());
  server->advertiseOnDisconnect(true);
  hid = new BLEHIDDevice(server);
  hid->manufacturer()->setValue("SBUHacks");
  hid->pnp(0x02, 0xE502, 0xA111, 0x0210);
  hid->hidInfo(0x00, 0x01);
  hid->reportMap((uint8_t*)HID_MAP, sizeof(HID_MAP));
  keyboardReport = hid->inputReport(1);
  hid->inputReport(2);
  hid->inputReport(3);
  hid->setBatteryLevel(100);
  hid->startServices();

  BLEAdvertising* advertising = BLEDevice::getAdvertising();
  advertising->setAppearance(0x03C1);   // keyboard
  advertising->addServiceUUID(hid->hidService()->getUUID());
  advertising->setScanResponse(true);
  BLEDevice::startAdvertising();
}

void sendKeys(uint8_t key) {
  uint8_t keyboard[8] = {0, 0, key, 0, 0, 0, 0, 0};
  keyboardReport->setValue(keyboard, 8);
  keyboardReport->notify();
}

void tapKey(uint8_t key) {
  sendKeys(key);
  delay(12);
  sendKeys(0);
}

void pressKey(Key key) {
  if (!computerConnected) return;
  switch (key) {
    case NEXT_PAGE:     tapKey(KEY_PAGE_DOWN); break;
    case PREVIOUS_PAGE: tapKey(KEY_PAGE_UP); break;
    case OSWALD:        tapKey(KEY_F18); break;
  }
}

const char* KEY_NAMES[] = {"next page", "previous page", "ask Oswald"};

Key repeatKey;
bool repeating = false;
uint32_t nextRepeat = 0;

// Runs the control for a trigger like "index hold". Returns true if there was one.
bool runControl(const char* trigger) {
  for (const Control& c : CONTROLS) {
    if (strcmp(c.trigger, trigger) != 0) continue;
    pressKey(c.key);
    noteGesture(computerConnected ? KEY_NAMES[c.key] : "Pair Board first");
    if (c.repeats) {
      repeating = true;
      repeatKey = c.key;
      nextRepeat = millis() + REPEAT_MS;
    }
    return true;
  }
  return false;
}

void updateRepeat(uint32_t now) {
  if (repeating && fingersDown && (int32_t)(now - nextRepeat) >= 0) {
    nextRepeat += REPEAT_MS;
    pressKey(repeatKey);
  }
}

// =====================================================================
// Fingers (touch to thumb = GND)
// Every finger that touches before the hold (or before letting go) is part of the combo.
// =====================================================================
uint8_t combo = 0;
uint32_t comboStart = 0;
bool holdSent = false;

void setupPads() {
  for (int i = 0; i < PAD_COUNT; i++) pinMode(pads[i].pin, INPUT_PULLUP);
}

void fingerNames(uint8_t fingers, char* out) {
  out[0] = '\0';
  for (int i = 0; i < PAD_COUNT; i++) {
    if (!(fingers & (1 << i))) continue;
    if (out[0]) strcat(out, "+");
    strcat(out, pads[i].name);
  }
}

uint8_t readPads(uint32_t now) {
  uint8_t down = 0;
  for (int i = 0; i < PAD_COUNT; i++) {
    Pad &p = pads[i];
    bool touching = digitalRead(p.pin) == LOW;
    if (touching != p.raw) {
      p.raw = touching;
      p.changedAt = now;
    }
    if (now - p.changedAt >= DEBOUNCE_MS) p.down = touching;
    if (p.down) down |= 1 << i;
  }
  return down;
}

void updatePads(uint32_t now) {
  uint8_t down = readPads(now);
  if (down != fingersDown) {
    fingersDown = down;
    if (!down) repeating = false;
  }

  if (!combo) {
    if (!down) return;
    combo = down;
    comboStart = now;
    holdSent = false;
  }
  if (!holdSent) combo |= down;

  char names[40], trigger[48];
  fingerNames(combo, names);
  if (!down) {
    if (!holdSent) runControl(names);
    combo = 0;
  } else if (!holdSent && now - comboStart >= HOLD_MS) {
    holdSent = true;
    snprintf(trigger, sizeof(trigger), "%s hold", names);
    runControl(trigger);
  }
}

// =====================================================================
void setup() {
  Serial.begin(115200);
  setupPads();
  setupBluetooth();
  Serial.println("Board ready. Pair \"Board\" in the computer's Bluetooth settings.");
}

void loop() {
  uint32_t now = millis();
  updatePads(now);
  updateRepeat(now);
}
