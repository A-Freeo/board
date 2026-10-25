#pragma once
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <string>
#include <vector>
#define LOW 0
#define HIGH 1
#define INPUT_PULLUP 2
#define OUTPUT 1
extern uint32_t fakeNow;
extern int pinState[64];
inline uint32_t millis() { return fakeNow; }
inline void delay(uint32_t) {}
inline int digitalRead(int pin) { return pinState[pin]; }
inline void digitalWrite(int, int) {}
inline void pinMode(int, int) {}
struct FakeSerial { void begin(int) {} void println(const char* s) { lines.push_back(s); } std::vector<std::string> lines; };
extern FakeSerial Serial;
