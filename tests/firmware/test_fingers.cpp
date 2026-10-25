// The board's finger logic on this computer, with fake pins and fake Bluetooth. Run tests/run_firmware_tests.sh
#include "fw.cpp"
uint32_t fakeNow = 0; int pinState[64]; FakeSerial Serial; std::vector<int> sentKeys; BLEServer theServer;
const char* name(int k) { switch (k) { case 0: return "up"; case 0x4E: return "PgDn"; case 0x4B: return "PgUp"; case 0x6D: return "F18"; } return "?"; }
std::string keys() { std::string out; for (int k : sentKeys) { out += name(k); out += " "; } return out; }
void run(uint32_t ms) { for (uint32_t t = 0; t < ms; t += 5) { fakeNow += 5; loop(); } }
int pinOf(const char* f) { for (int i = 0; i < PAD_COUNT; i++) if (!strcmp(pads[i].name, f)) return pads[i].pin; return -1; }
void touch(const char* f, bool on) { pinState[pinOf(f)] = on ? LOW : HIGH; }
int fails = 0;
void check(bool ok, const char* what) { printf("%s %s  [%s]\n", ok ? "PASS" : "FAIL", what, keys().c_str()); fails += !ok; sentKeys.clear(); }
int main() {
  for (int i = 0; i < 64; i++) pinState[i] = HIGH;
  setup(); run(100);
  check(pinOf("index tip") == 13 && pinOf("index lower") == 14 && pinOf("ring") == 27 && PAD_COUNT == 3,
        "three pads: index tip on GPIO 13, index lower on GPIO 14, ring on GPIO 27");
  touch("index tip", true); run(150); touch("index tip", false); run(100);
  check(keys() == "", "nothing is typed before the computer pairs");
  theServer.cb->onConnect(&theServer); run(50);
  touch("index tip", true); run(150); touch("index tip", false); run(100);
  check(keys() == "PgDn up ", "index tip tap = Page Down");
  touch("index lower", true); run(150); touch("index lower", false); run(100);
  check(keys() == "PgUp up ", "index lower tap = Page Up");
  touch("ring", true); run(150); touch("ring", false); run(100);
  check(keys() == "F18 up ", "ring tap = F18 (ask Oswald)");
  touch("ring", true); run(1500); touch("ring", false); run(100);
  check(keys() == "F18 up ", "ring held = one F18, no repeats");
  touch("index tip", true); run(40); touch("index lower", true); run(150); touch("index tip", false); touch("index lower", false); run(100);
  check(keys() == "", "both index pads at once = nothing");
  touch("index tip", true); run(1400); touch("index tip", false); run(100);
  check(sentKeys.size() >= 8 && keys().find("PgUp") == std::string::npos, "index tip hold keeps paging forward");
  touch("index lower", true); run(1400); touch("index lower", false); run(100);
  check(sentKeys.size() >= 8 && keys().find("PgDn") == std::string::npos, "index lower hold keeps paging back");
  printf(fails ? "%d FAILED\n" : "ALL PASSED\n", fails);
  return fails ? 1 : 0;
}
