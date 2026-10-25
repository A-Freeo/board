#pragma once
#include "BLEDevice.h"
struct BLEHIDDevice {
  BLEHIDDevice(BLEServer*) {}
  BLECharacteristic* manufacturer() { static BLECharacteristic c; return &c; }
  void pnp(int, int, int, int) {}
  void hidInfo(int, int) {}
  void reportMap(uint8_t*, size_t) {}
  BLECharacteristic* inputReport(int id) { static BLECharacteristic r[4]; return &r[id]; }
  void setBatteryLevel(int) {}
  void startServices() {}
  BLEService* hidService() { static BLEService s; return &s; }
};
