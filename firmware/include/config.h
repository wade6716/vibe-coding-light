#ifndef CONFIG_H
#define CONFIG_H

// GPIO pins — active HIGH (common cathode wiring)
#define PIN_RED    14  // D5
#define PIN_YELLOW 12  // D6
#define PIN_GREEN  13  // D7
#define LED_ON     HIGH
#define LED_OFF    LOW

// Network
#define HOSTNAME      "signal-light"
#define AP_SSID       "Signal-Light-Setup"

// Flash timing
#define FLASH_ON_MS   120
#define FLASH_OFF_MS  100

// Notice flash timing
#define NOTICE_ON_MS  180
#define NOTICE_OFF_MS 140
#define NOTICE_LOOPS  6

// Work cycle: 600ms per color phase (green -> yellow -> red)
#define WORK_CYCLE_PHASE_MS 600

#endif // CONFIG_H
