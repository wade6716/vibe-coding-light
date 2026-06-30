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

// Session management
#define SESSION_TTL_SECONDS  86400UL   // 24 hours
#define MAX_SESSIONS         32
#define IDLE_SLEEP_MS        600000UL  // 10 minutes

// Work cycle soft-pulse (PWM 0-1023, active-high)
// Reference brightness: 0.10, 0.18, 0.32, 0.50, 0.68, 0.50, 0.32, 0.18, 0.10
// PWM = (int)(brightness * 1023)
#define PULSE_STEPS 9
static const int PULSE_PWM[PULSE_STEPS] = {102, 185, 328, 512, 696, 512, 328, 185, 102};
#define PULSE_STEP_MS 160

// Flash timing
#define FLASH_ON_MS   120
#define FLASH_OFF_MS  100

// Notice flash timing
#define NOTICE_ON_MS  180
#define NOTICE_OFF_MS 140
#define NOTICE_LOOPS  6

#endif // CONFIG_H
