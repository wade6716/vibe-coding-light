/*
 * Vibecoding Signal Light — ESP8266 firmware (pattern player)
 *
 * A simple LED pattern player.  All session management, aggregation, and
 * business logic lives in the Python client.  The ESP8266 just plays the
 * pattern it's told to play.
 *
 * HTTP API:
 *   POST /pattern  {"pattern":"flash_yellow","timeout":300}
 *   GET  /status   {"pattern":"...","leds":{"red":bool,"yellow":bool,"green":bool}}
 *   POST /reset    {"ok":true}
 */

#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>
#include <ESP8266mDNS.h>
#include <WiFiManager.h>
#include <ArduinoJson.h>
#include "config.h"

// ---------------------------------------------------------------------------
// Display patterns
// ---------------------------------------------------------------------------

enum class DisplayPattern : uint8_t {
    OFF,
    STEADY_GREEN,
    WORK_CYCLE,
    FLASH_YELLOW,
    FLASH_RED,
    NOTICE_FLASH_GREEN,
    INVALID
};

// ---------------------------------------------------------------------------
// Global state
// ---------------------------------------------------------------------------

DisplayPattern current_pattern = DisplayPattern::OFF;

// Animation state
unsigned long last_step_time = 0;
int animation_step = 0;
int animation_loop_count = 0;

// Timeout
int timeout_seconds = 0;
unsigned long timeout_start = 0;

ESP8266WebServer server(80);

// ---------------------------------------------------------------------------
// Pattern name parsing
// ---------------------------------------------------------------------------

DisplayPattern parse_pattern(const char *name) {
    if (strcmp(name, "off") == 0)           return DisplayPattern::OFF;
    if (strcmp(name, "green_on") == 0)      return DisplayPattern::STEADY_GREEN;
    if (strcmp(name, "work_cycle") == 0)    return DisplayPattern::WORK_CYCLE;
    if (strcmp(name, "flash_yellow") == 0)  return DisplayPattern::FLASH_YELLOW;
    if (strcmp(name, "flash_red") == 0)     return DisplayPattern::FLASH_RED;
    if (strcmp(name, "notice_green") == 0)  return DisplayPattern::NOTICE_FLASH_GREEN;
    return DisplayPattern::INVALID;
}

const char *pattern_name(DisplayPattern p) {
    switch (p) {
        case DisplayPattern::OFF:               return "off";
        case DisplayPattern::STEADY_GREEN:      return "green_on";
        case DisplayPattern::WORK_CYCLE:        return "work_cycle";
        case DisplayPattern::FLASH_YELLOW:      return "flash_yellow";
        case DisplayPattern::FLASH_RED:         return "flash_red";
        case DisplayPattern::NOTICE_FLASH_GREEN: return "notice_green";
        default:                                return "unknown";
    }
}

// ---------------------------------------------------------------------------
// LED control
// ---------------------------------------------------------------------------

void set_leds(bool r, bool y, bool g) {
    digitalWrite(PIN_RED,    r ? LED_ON : LED_OFF);
    digitalWrite(PIN_YELLOW, y ? LED_ON : LED_OFF);
    digitalWrite(PIN_GREEN,  g ? LED_ON : LED_OFF);
}

void all_off() {
    set_leds(false, false, false);
}

void apply_static_pattern(DisplayPattern p) {
    switch (p) {
        case DisplayPattern::STEADY_GREEN:
            set_leds(false, false, true);
            break;
        case DisplayPattern::OFF:
        default:
            all_off();
            break;
    }
}

// ---------------------------------------------------------------------------
// Animation state machine
// ---------------------------------------------------------------------------

void animation_tick() {
    unsigned long now = millis();

    switch (current_pattern) {
        // --- Static patterns: nothing to tick ---
        case DisplayPattern::STEADY_GREEN:
        case DisplayPattern::OFF:
            return;

        // --- Work cycle: green -> yellow -> red, 600ms per phase ---
        case DisplayPattern::WORK_CYCLE: {
            if (now - last_step_time < WORK_CYCLE_PHASE_MS) return;
            last_step_time = now;

            int phase = animation_step % 3;
            set_leds(phase == 2, phase == 1, phase == 0);
            animation_step++;
            break;
        }

        // --- Flash yellow ---
        case DisplayPattern::FLASH_YELLOW: {
            bool is_on = (animation_step % 2 == 0);
            unsigned long interval = is_on ? FLASH_ON_MS : FLASH_OFF_MS;
            if (now - last_step_time < interval) return;
            last_step_time = now;

            if (is_on) {
                set_leds(false, true, false);
            } else {
                all_off();
            }
            animation_step++;
            if (animation_step % 2 == 0) animation_loop_count++;
            break;
        }

        // --- Flash red ---
        case DisplayPattern::FLASH_RED: {
            bool is_on = (animation_step % 2 == 0);
            unsigned long interval = is_on ? FLASH_ON_MS : FLASH_OFF_MS;
            if (now - last_step_time < interval) return;
            last_step_time = now;

            if (is_on) {
                set_leds(true, false, false);
            } else {
                all_off();
            }
            animation_step++;
            if (animation_step % 2 == 0) animation_loop_count++;
            break;
        }

        // --- Notice flash green: blink N times then revert to OFF ---
        case DisplayPattern::NOTICE_FLASH_GREEN: {
            bool is_on = (animation_step % 2 == 0);
            unsigned long interval = is_on ? NOTICE_ON_MS : NOTICE_OFF_MS;
            if (now - last_step_time < interval) return;
            last_step_time = now;

            if (is_on) {
                set_leds(false, false, true);
            } else {
                all_off();
            }
            animation_step++;
            if (animation_step % 2 == 0) {
                animation_loop_count++;
                if (animation_loop_count >= NOTICE_LOOPS) {
                    current_pattern = DisplayPattern::OFF;
                    all_off();
                    animation_step = 0;
                    animation_loop_count = 0;
                }
            }
            break;
        }

        default:
            break;
    }
}

// ---------------------------------------------------------------------------
// HTTP handlers
// ---------------------------------------------------------------------------

void handle_pattern() {
    if (server.method() != HTTP_POST) {
        server.send(405, "application/json", "{\"ok\":false,\"error\":\"method not allowed\"}");
        return;
    }

    JsonDocument doc;
    DeserializationError err = deserializeJson(doc, server.arg("plain"));
    if (err) {
        server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid json\"}");
        return;
    }

    const char *pattern_str = doc["pattern"] | "";
    DisplayPattern new_pattern = parse_pattern(pattern_str);
    if (new_pattern == DisplayPattern::INVALID) {
        String resp;
        JsonDocument rdoc;
        rdoc["ok"] = false;
        rdoc["error"] = String("unknown pattern: ") + pattern_str;
        serializeJson(rdoc, resp);
        server.send(400, "application/json", resp);
        return;
    }

    // Apply new pattern
    current_pattern = new_pattern;
    animation_step = 0;
    animation_loop_count = 0;
    last_step_time = millis();

    // Timeout
    timeout_seconds = doc["timeout"] | 0;
    if (timeout_seconds > 0) {
        timeout_start = millis();
    }

    // Apply static patterns immediately
    if (current_pattern == DisplayPattern::STEADY_GREEN ||
        current_pattern == DisplayPattern::OFF) {
        apply_static_pattern(current_pattern);
    }

    Serial.printf("[PATTERN] %s (timeout=%ds)\n", pattern_str, timeout_seconds);

    // Response
    String resp;
    JsonDocument rdoc;
    rdoc["ok"] = true;
    rdoc["pattern"] = pattern_str;
    serializeJson(rdoc, resp);
    server.send(200, "application/json", resp);
}

void handle_status() {
    String resp;
    JsonDocument doc;
    doc["pattern"] = pattern_name(current_pattern);

    JsonObject leds = doc["leds"].to<JsonObject>();
    leds["red"]    = (digitalRead(PIN_RED)    == LED_ON);
    leds["yellow"] = (digitalRead(PIN_YELLOW) == LED_ON);
    leds["green"]  = (digitalRead(PIN_GREEN)  == LED_ON);

    serializeJson(doc, resp);
    server.send(200, "application/json", resp);
}

void handle_reset() {
    current_pattern = DisplayPattern::OFF;
    all_off();
    timeout_seconds = 0;
    animation_step = 0;
    animation_loop_count = 0;
    Serial.println("[RESET] All off");
    server.send(200, "application/json", "{\"ok\":true}");
}

void handle_cors() {
    server.sendHeader("Access-Control-Allow-Origin", "*");
    server.sendHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
    server.sendHeader("Access-Control-Allow-Headers", "Content-Type");
    server.send(204);
}

// ---------------------------------------------------------------------------
// setup() and loop()
// ---------------------------------------------------------------------------

void setup() {
    Serial.begin(115200);
    Serial.println();
    Serial.println("=== Signal Light (Pattern Player) ===");

    // GPIO
    pinMode(PIN_RED,    OUTPUT);
    pinMode(PIN_YELLOW, OUTPUT);
    pinMode(PIN_GREEN,  OUTPUT);
    all_off();

    // WiFi — captive portal for first-time setup
    WiFiManager wifiManager;
    WiFi.hostname(HOSTNAME);
    wifiManager.autoConnect(AP_SSID);
    Serial.printf("Connected: %s\n", WiFi.localIP().toString().c_str());

    // mDNS
    if (MDNS.begin(HOSTNAME)) {
        Serial.printf("mDNS: http://%s.local\n", HOSTNAME);
    }

    // HTTP routes
    server.on("/pattern", HTTP_POST,    handle_pattern);
    server.on("/pattern", HTTP_OPTIONS, handle_cors);
    server.on("/status",  HTTP_GET,     handle_status);
    server.on("/reset",   HTTP_POST,    handle_reset);
    server.begin();
    Serial.println("HTTP server started");

    // Start with green on (idle)
    current_pattern = DisplayPattern::STEADY_GREEN;
    apply_static_pattern(DisplayPattern::STEADY_GREEN);
}

void loop() {
    server.handleClient();
    MDNS.update();
    animation_tick();

    // Timeout: revert to OFF if no new pattern arrives
    if (timeout_seconds > 0 && current_pattern != DisplayPattern::OFF) {
        if (millis() - timeout_start > (unsigned long)timeout_seconds * 1000UL) {
            Serial.println("[TIMEOUT] Reverting to off");
            current_pattern = DisplayPattern::OFF;
            all_off();
            timeout_seconds = 0;
        }
    }

    // WiFi reconnect
    static unsigned long last_wifi_check = 0;
    if (millis() - last_wifi_check > 30000) {
        last_wifi_check = millis();
        if (WiFi.status() != WL_CONNECTED) {
            Serial.println("WiFi disconnected, reconnecting...");
            WiFi.reconnect();
        }
    }
}
