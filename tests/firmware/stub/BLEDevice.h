#pragma once
#include "Arduino.h"
#define ESP_IO_CAP_NONE 3
extern std::vector<int> sentKeys;
struct BLEUUID {};
struct BLECharacteristic {
  void setValue(uint8_t* data, size_t len) { last = data[2]; }
  void setValue(const char*) {}
  void notify() { sentKeys.push_back(last); }
  int last = 0;
};
struct BLEService { BLEUUID getUUID() { return BLEUUID(); } };
struct BLEServer;
struct BLEServerCallbacks { virtual void onConnect(BLEServer*) {} virtual void onDisconnect(BLEServer*) {} virtual ~BLEServerCallbacks() {} };
struct BLEServer { BLEServerCallbacks* cb = nullptr; void setCallbacks(BLEServerCallbacks* c) { cb = c; } void advertiseOnDisconnect(bool) {} };
struct BLEAdvertising { void setAppearance(int) {} void addServiceUUID(BLEUUID) {} void setScanResponse(bool) {} };
extern BLEServer theServer;
struct BLEDevice {
  static void init(const char*) {}
  static BLEServer* createServer() { return &theServer; }
  static BLEAdvertising* getAdvertising() { static BLEAdvertising a; return &a; }
  static void startAdvertising() {}
};
struct BLESecurity { void setCapability(int) {} void setAuthenticationMode(bool, bool, bool) {} };
