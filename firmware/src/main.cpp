/*
 * Vibecoding Signal Light — ESP8266 firmware
 *
 * WiFi-controlled traffic signal for AI coding agent status.
 * Receives HTTP POST /signal from the Python client and drives
 * red/yellow/green LEDs with non-blocking animations.
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
    NOTICE_FLASH_GREEN
};

// ---------------------------------------------------------------------------
// Session store
// ---------------------------------------------------------------------------

struct SessionEntry {
    char session_id[48];
    char signal[16];
    unsigned long updated_at;
};

SessionEntry sessions[MAX_SESSIONS];
int session_count = 0;

// ---------------------------------------------------------------------------
// Global state
// ---------------------------------------------------------------------------

DisplayPattern current_pattern = DisplayPattern::STEADY_GREEN;
char aggregate_signal[16] = "idle";

// Animation state
unsigned long last_step_time = 0;
int animation_step = 0;
int animation_loop_count = 0;
int animation_max_loops = 0;  // 0 = infinite

// Idle sleep
unsigned long idle_since = 0;
bool idle_sleep_armed = false;

// Pending notice flash (triggered by session_end)
bool pending_notice = false;
char notice_restore_signal[16] = "idle";

ESP8266WebServer server(80);

void set_leds(bool r, bool y, bool g);
void apply_static_pattern(DisplayPattern p);
void compute_aggregate();

// ---------------------------------------------------------------------------
// Signal-to-pattern mapping
// ---------------------------------------------------------------------------

DisplayPattern signal_to_pattern(const char *signal) {
    if (strcmp(signal, "idle") == 0 || strcmp(signal, "session_start") == 0 ||
        strcmp(signal, "session_end") == 0) {
        return DisplayPattern::STEADY_GREEN;
    }
    if (strcmp(signal, "thinking") == 0 || strcmp(signal, "working") == 0 ||
        strcmp(signal, "tool_done") == 0) {
        return DisplayPattern::WORK_CYCLE;
    }
    if (strcmp(signal, "attention") == 0 || strcmp(signal, "permission") == 0 ||
        strcmp(signal, "done") == 0) {
        return DisplayPattern::FLASH_YELLOW;
    }
    if (strcmp(signal, "blocked") == 0) {
        return DisplayPattern::FLASH_RED;
    }
    if (strcmp(signal, "session_done") == 0) {
        return DisplayPattern::NOTICE_FLASH_GREEN;
    }
    return DisplayPattern::OFF;
}

// ---------------------------------------------------------------------------
// Session management
// ---------------------------------------------------------------------------

int find_session(const char *session_id) {
    for (int i = 0; i < session_count; i++) {
        if (strcmp(sessions[i].session_id, session_id) == 0) {
            return i;
        }
    }
    return -1;
}

void upsert_session(const char *session_id, const char *signal) {
    int idx = find_session(session_id);
    if (idx >= 0) {
        strncpy(sessions[idx].signal, signal, sizeof(sessions[idx].signal) - 1);
        sessions[idx].signal[sizeof(sessions[idx].signal) - 1] = '\0';
        sessions[idx].updated_at = millis();
        return;
    }
    if (session_count >= MAX_SESSIONS) {
        // Evict oldest
        int oldest = 0;
        for (int i = 1; i < session_count; i++) {
            if (sessions[i].updated_at < sessions[oldest].updated_at) {
                oldest = i;
            }
        }
        idx = oldest;
    } else {
        idx = session_count++;
    }
    strncpy(sessions[idx].session_id, session_id, sizeof(sessions[idx].session_id) - 1);
    sessions[idx].session_id[sizeof(sessions[idx].session_id) - 1] = '\0';
    strncpy(sessions[idx].signal, signal, sizeof(sessions[idx].signal) - 1);
    sessions[idx].signal[sizeof(sessions[idx].signal) - 1] = '\0';
    sessions[idx].updated_at = millis();
}

void remove_session(const char *session_id) {
    int idx = find_session(session_id);
    if (idx < 0) return;
    sessions[idx] = sessions[--session_count];
}

void prune_expired_sessions() {
    unsigned long now = millis();
    unsigned long ttl_ms = SESSION_TTL_SECONDS * 1000UL;
    int i = 0;
    int initial_count = session_count;
    while (i < session_count) {
        if (now - sessions[i].updated_at > ttl_ms) {
            sessions[i] = sessions[--session_count];
        } else {
            i++;
        }
    }
    if (session_count != initial_count) {
        compute_aggregate();
    }
}

bool is_red_signal(const char *sig) {
    return strcmp(sig, "blocked") == 0;
}

bool is_yellow_signal(const char *sig) {
    return strcmp(sig, "permission") == 0 || strcmp(sig, "attention") == 0 ||
           strcmp(sig, "done") == 0;
}

bool is_working_signal(const char *sig) {
    return strcmp(sig, "thinking") == 0 || strcmp(sig, "working") == 0 ||
           strcmp(sig, "tool_done") == 0;
}

bool is_urgent_signal(const char *sig) {
    return strcmp(sig, "permission") == 0 || strcmp(sig, "blocked") == 0;
}

void compute_aggregate() {
    const char *agg = "idle";
    for (int i = 0; i < session_count; i++) {
        if (is_red_signal(sessions[i].signal)) {
            agg = "blocked";
            break;
        }
    }
    if (strcmp(agg, "idle") == 0) {
        for (int i = 0; i < session_count; i++) {
            if (strcmp(sessions[i].signal, "permission") == 0) {
                agg = "permission";
                break;
            }
        }
    }
    if (strcmp(agg, "idle") == 0) {
        for (int i = 0; i < session_count; i++) {
            if (is_yellow_signal(sessions[i].signal)) {
                agg = "attention";
                break;
            }
        }
    }
    if (strcmp(agg, "idle") == 0) {
        for (int i = 0; i < session_count; i++) {
            if (is_working_signal(sessions[i].signal)) {
                agg = "working";
                break;
            }
        }
    }

    if (strcmp(agg, aggregate_signal) != 0) {
        strncpy(aggregate_signal, agg, sizeof(aggregate_signal) - 1);
        aggregate_signal[sizeof(aggregate_signal) - 1] = '\0';
        DisplayPattern new_pattern = signal_to_pattern(agg);
        if (new_pattern != current_pattern) {
            current_pattern = new_pattern;
            animation_step = 0;
            animation_loop_count = 0;
            last_step_time = millis();
            
            // If transitioning to a static pattern, apply it immediately
            if (current_pattern == DisplayPattern::STEADY_GREEN ||
                current_pattern == DisplayPattern::OFF) {
                apply_static_pattern(current_pattern);
            }

            // Determine max loops for flash patterns
            if (current_pattern == DisplayPattern::FLASH_YELLOW ||
                current_pattern == DisplayPattern::FLASH_RED) {
                animation_max_loops = 0;  // infinite (aggregate-driven)
            } else if (current_pattern == DisplayPattern::NOTICE_FLASH_GREEN) {
                animation_max_loops = NOTICE_LOOPS;
            } else {
                animation_max_loops = 0;
            }
        }
    }

    // Manage idle sleep
    if (strcmp(agg, "idle") == 0) {
        if (!idle_sleep_armed) {
            idle_sleep_armed = true;
            idle_since = millis();
        }
    } else {
        idle_sleep_armed = false;
    }
}

// ---------------------------------------------------------------------------
// LED control
// ---------------------------------------------------------------------------

void set_leds(bool r, bool y, bool g) {
    digitalWrite(PIN_RED,   r ? LED_ON : LED_OFF);
    digitalWrite(PIN_YELLOW, y ? LED_ON : LED_OFF);
    digitalWrite(PIN_GREEN,  g ? LED_ON : LED_OFF);
}

void set_leds_pwm(int r, int y, int g) {
    analogWrite(PIN_RED,   r);
    analogWrite(PIN_YELLOW, y);
    analogWrite(PIN_GREEN,  g);
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
        case DisplayPattern::STEADY_GREEN:
        case DisplayPattern::OFF:
            // Static — nothing to tick
            return;

        case DisplayPattern::WORK_CYCLE: {
            if (now - last_step_time < 600) return; // 跑马灯切换间隔 600ms
            last_step_time = now;

            int phase = animation_step % 3; // 0=green, 1=yellow, 2=red

            if (phase == 0) {
                set_leds(false, false, true);  // 绿灯亮
            } else if (phase == 1) {
                set_leds(false, true, false);  // 黄灯亮
            } else {
                set_leds(true, false, false);  // 红灯亮
            }

            animation_step++;
            if (animation_step >= 3) {
                animation_step = 0;
                animation_loop_count++;
            }
            break;
        }

        case DisplayPattern::FLASH_YELLOW:
        case DisplayPattern::FLASH_RED: {
            bool is_on_step = (animation_step % 2 == 0);
            unsigned long duration = is_on_step ? FLASH_ON_MS : FLASH_OFF_MS;
            if (now - last_step_time < duration) return;
            last_step_time = now;

            if (is_on_step) {
                if (current_pattern == DisplayPattern::FLASH_YELLOW) {
                    set_leds(false, true, false);
                } else {
                    set_leds(true, false, false);
                }
            } else {
                all_off();
            }

            animation_step++;
            if (animation_step >= 2) {
                animation_step = 0;
                animation_loop_count++;
                if (animation_max_loops > 0 && animation_loop_count >= animation_max_loops) {
                    all_off();
                }
            }
            break;
        }

        case DisplayPattern::NOTICE_FLASH_GREEN: {
            bool is_on_step = (animation_step % 2 == 0);
            unsigned long duration = is_on_step ? NOTICE_ON_MS : NOTICE_OFF_MS;
            if (now - last_step_time < duration) return;
            last_step_time = now;

            if (is_on_step) {
                set_leds(false, false, true);
            } else {
                all_off();
            }

            animation_step++;
            if (animation_step >= 2) {
                animation_step = 0;
                animation_loop_count++;
                if (animation_loop_count >= NOTICE_LOOPS) {
                    // Restore aggregate pattern
                    current_pattern = signal_to_pattern(aggregate_signal);
                    animation_step = 0;
                    animation_loop_count = 0;
                    last_step_time = now;
                    if (current_pattern == DisplayPattern::STEADY_GREEN) {
                        set_leds(false, false, true);
                    } else if (current_pattern == DisplayPattern::OFF) {
                        all_off();
                    }
                    // For repeating patterns, the next tick will start the animation
                }
            }
            break;
        }
    }
}

// ---------------------------------------------------------------------------
// Signal validation
// ---------------------------------------------------------------------------

bool is_valid_signal(const char *signal) {
    static const char *valid[] = {
        "idle", "thinking", "working", "tool_done",
        "attention", "permission", "blocked", "done",
        "session_start", "session_end", "session_done", "off", "turn_end",
        nullptr
    };
    for (int i = 0; valid[i] != nullptr; i++) {
        if (strcmp(signal, valid[i]) == 0) return true;
    }
    return false;
}

// ---------------------------------------------------------------------------
// HTTP handlers
// ---------------------------------------------------------------------------

void handle_signal() {
    if (server.method() != HTTP_POST) {
        server.send(405, "application/json", "{\"ok\":false,\"error\":\"method not allowed\"}");
        return;
    }

    JsonDocument doc;
    DeserializationError err = deserializeJson(doc, server.arg("plain"));
    if (err) {
        Serial.printf("[SIGNAL] JSON parse error: %s\n", err.c_str());
        server.send(400, "application/json", "{\"ok\":false,\"error\":\"invalid json\"}");
        return;
    }

    const char *signal = doc["signal"] | "";
    if (!is_valid_signal(signal)) {
        Serial.printf("[SIGNAL] unknown signal: \"%s\"\n", signal);
        String resp;
        JsonDocument rdoc;
        rdoc["ok"] = false;
        rdoc["error"] = String("unknown signal: ") + signal;
        serializeJson(rdoc, resp);
        server.send(400, "application/json", resp);
        return;
    }

    const char *session_id = doc["session_id"] | "global";
    if (strlen(session_id) == 0) session_id = "global";

    Serial.printf("[SIGNAL] %s (session=%s)\n", signal, session_id);

    bool should_notice = false;

    // Special signal handling
    if (strcmp(signal, "session_end") == 0 || strcmp(signal, "off") == 0 || strcmp(signal, "session_done") == 0) {
        bool existed = find_session(session_id) >= 0;
        remove_session(session_id);
        if (existed && (strcmp(signal, "session_end") == 0 || strcmp(signal, "session_done") == 0)) {
            should_notice = true;
        }
    } else if (strcmp(signal, "turn_end") == 0) {
        int idx = find_session(session_id);
        if (idx >= 0) {
            if (!is_urgent_signal(sessions[idx].signal)) {
                should_notice = true;
                remove_session(session_id);
            }
            // urgent sessions (permission/blocked) are kept
        }
    } else {
        upsert_session(session_id, signal);
    }

    // Recompute aggregate
    char prev_agg[16];
    strncpy(prev_agg, aggregate_signal, sizeof(prev_agg));
    compute_aggregate();

    if (strcmp(prev_agg, aggregate_signal) != 0) {
        Serial.printf("[AGGREGATE] %s -> %s\n", prev_agg, aggregate_signal);
    }

    // Handle notice flash for session_end / turn_end
    if (should_notice) {
        bool agg_is_red = strcmp(aggregate_signal, "blocked") == 0;
        bool agg_is_yellow = strcmp(aggregate_signal, "permission") == 0 ||
                             strcmp(aggregate_signal, "attention") == 0;
        if (!agg_is_red && !agg_is_yellow) {
            // Start notice flash, then restore aggregate
            current_pattern = DisplayPattern::NOTICE_FLASH_GREEN;
            animation_step = 0;
            animation_loop_count = 0;
            animation_max_loops = NOTICE_LOOPS;
            last_step_time = millis();
        }
    }

    // Build response
    String resp;
    JsonDocument rdoc;
    rdoc["signal"] = signal;
    rdoc["session_id"] = session_id;
    rdoc["aggregate"] = aggregate_signal;
    rdoc["ok"] = true;
    serializeJson(rdoc, resp);
    server.send(200, "application/json", resp);
}

void handle_status() {
    String resp;
    JsonDocument doc;
    doc["aggregate"] = aggregate_signal;

    const char *pattern_names[] = {"off", "steady_green", "work_cycle", "flash_yellow", "flash_red", "notice_flash_green"};
    doc["pattern"] = pattern_names[(int)current_pattern];

    JsonObject sess = doc["sessions"].to<JsonObject>();
    unsigned long now = millis();
    for (int i = 0; i < session_count; i++) {
        JsonObject s = sess[sessions[i].session_id].to<JsonObject>();
        s["signal"] = sessions[i].signal;
        s["age_seconds"] = (now - sessions[i].updated_at) / 1000UL;
    }

    serializeJson(doc, resp);
    server.send(200, "application/json", resp);
}

void handle_reset() {
    int cleared = session_count;
    Serial.printf("[RESET] cleared %d session(s)\n", cleared);
    session_count = 0;
    memset(sessions, 0, sizeof(sessions));
    strncpy(aggregate_signal, "idle", sizeof(aggregate_signal) - 1);
    current_pattern = DisplayPattern::OFF;
    all_off();
    idle_sleep_armed = false;

    String resp;
    JsonDocument doc;
    doc["ok"] = true;
    doc["sessions_cleared"] = cleared;
    serializeJson(doc, resp);
    server.send(200, "application/json", resp);
}

// ---------------------------------------------------------------------------
// Setup & loop
// ---------------------------------------------------------------------------

void setup() {
    Serial.begin(115200);
    Serial.println();
    Serial.println("Signal Light starting...");

    // GPIO
    pinMode(PIN_RED, OUTPUT);
    pinMode(PIN_YELLOW, OUTPUT);
    pinMode(PIN_GREEN, OUTPUT);
    all_off();

    // WiFi via WiFiManager
    WiFiManager wm;
    wm.setHostname(HOSTNAME);
    bool connected = wm.autoConnect(AP_SSID);
    if (!connected) {
        Serial.println("WiFi failed, restarting...");
        ESP.restart();
    }
    Serial.print("Connected! IP: ");
    Serial.println(WiFi.localIP());

    // mDNS
    if (MDNS.begin(HOSTNAME)) {
        Serial.printf("mDNS: http://%s.local\n", HOSTNAME);
    }

    // HTTP routes
    server.on("/signal", HTTP_POST, handle_signal);
    server.on("/signal", HTTP_OPTIONS, []() {
        server.sendHeader("Access-Control-Allow-Origin", "*");
        server.sendHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
        server.sendHeader("Access-Control-Allow-Headers", "Content-Type");
        server.send(204);
    });
    server.on("/status", HTTP_GET, handle_status);
    server.on("/reset", HTTP_POST, handle_reset);
    server.begin();
    Serial.println("HTTP server started");

    // Initial state
    current_pattern = DisplayPattern::STEADY_GREEN;
    set_leds(false, false, true);
    idle_since = millis();
    idle_sleep_armed = true;
}

void loop() {
    server.handleClient();
    MDNS.update();
    animation_tick();

    // Idle sleep: turn off LEDs after prolonged idle
    if (idle_sleep_armed && current_pattern == DisplayPattern::STEADY_GREEN &&
        millis() - idle_since > IDLE_SLEEP_MS) {
        current_pattern = DisplayPattern::OFF;
        all_off();
        idle_sleep_armed = false;
        Serial.println("Idle sleep: lights off");
    }

    // Prune expired sessions every ~10s (cheap enough for loop)
    static unsigned long last_prune = 0;
    if (millis() - last_prune > 10000) {
        last_prune = millis();
        prune_expired_sessions();
    }

    // WiFi reconnect check
    static unsigned long last_wifi_check = 0;
    if (millis() - last_wifi_check > 30000) {
        last_wifi_check = millis();
        if (WiFi.status() != WL_CONNECTED) {
            Serial.println("WiFi lost, reconnecting...");
            WiFi.reconnect();
        }
    }
}
