/*
 * ESP32 telemetry sender for the IoT Telemetry API.
 *
 * Reads a DHT22 and posts batched readings over HTTPS. Written against the
 * same API this repository serves, so the device side and the server side can
 * be verified together rather than assumed to match.
 *
 * Three things here exist because field devices misbehave:
 *
 *  1. Readings are buffered and sent as a batch, so a brief network outage
 *     costs latency instead of data.
 *  2. Each reading carries the timestamp of when it was sampled, not when it
 *     was sent. The server stores both.
 *  3. A failed POST keeps the buffer intact and retries on the next cycle.
 *     The server treats a replayed reading as a duplicate, not an error, so
 *     retrying is always safe.
 *
 * Libraries: WiFi, HTTPClient, ArduinoJson (>= 7), DHT sensor library, time.h
 */

#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <WiFi.h>
#include <time.h>

#include "DHT.h"

// ---------------------------------------------------------------- configure
static const char *WIFI_SSID = "your-wifi-ssid";
static const char *WIFI_PASSWORD = "your-wifi-password";

// Point this at your server. Use https:// in anything that leaves a lab bench.
static const char *API_BASE = "http://192.168.1.10:8000";

// Issued once when the device is registered. Treat it like a password.
static const char *DEVICE_API_KEY = "paste-the-api-key-from-POST-/devices";

static const uint8_t DHT_PIN = 4;
static const uint8_t DHT_TYPE = DHT22;

static const uint32_t SAMPLE_INTERVAL_MS = 30000;  // sample every 30 s
static const uint8_t BATCH_SIZE = 4;               // send after 4 samples
// ---------------------------------------------------------------------------

DHT dht(DHT_PIN, DHT_TYPE);

struct Sample {
  float temperature;
  float humidity;
  time_t sampledAt;
};

Sample buffer[BATCH_SIZE];
uint8_t bufferCount = 0;

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.printf("\nConnected, IP %s\n", WiFi.localIP().toString().c_str());
}

void syncClock() {
  // Without a real clock the device cannot timestamp its own samples, and the
  // server rejects anything outside its accepted window.
  configTime(0, 0, "pool.ntp.org", "time.nist.gov");
  Serial.print("Waiting for NTP");
  time_t now = time(nullptr);
  while (now < 1700000000) {  // any plausible epoch
    delay(500);
    Serial.print(".");
    now = time(nullptr);
  }
  Serial.println(" clock set");
}

String isoUtc(time_t t) {
  struct tm timeinfo;
  gmtime_r(&t, &timeinfo);
  char buf[25];
  strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", &timeinfo);
  return String(buf);
}

bool sendBatch() {
  if (bufferCount == 0) return true;
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi down, keeping buffer for the next cycle");
    return false;
  }

  JsonDocument doc;
  JsonArray readings = doc["readings"].to<JsonArray>();

  for (uint8_t i = 0; i < bufferCount; i++) {
    String stamp = isoUtc(buffer[i].sampledAt);

    JsonObject t = readings.add<JsonObject>();
    t["metric"] = "temperature";
    t["value"] = buffer[i].temperature;
    t["unit"] = "C";
    t["recorded_at"] = stamp;

    JsonObject h = readings.add<JsonObject>();
    h["metric"] = "humidity";
    h["value"] = buffer[i].humidity;
    h["unit"] = "%";
    h["recorded_at"] = stamp;
  }

  String body;
  serializeJson(doc, body);

  HTTPClient http;
  http.begin(String(API_BASE) + "/readings");
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-API-Key", DEVICE_API_KEY);
  http.setTimeout(10000);

  int status = http.POST(body);
  String response = http.getString();
  http.end();

  Serial.printf("POST /readings -> %d %s\n", status, response.c_str());

  if (status == 201) {
    bufferCount = 0;  // delivered; safe to drop
    return true;
  }
  if (status == 401) {
    // A wrong key will never succeed by retrying. Drop the buffer instead of
    // growing it forever, and make the reason obvious in the log.
    Serial.println("Device API key rejected. Check DEVICE_API_KEY.");
    bufferCount = 0;
    return false;
  }
  // Anything else (timeout, 5xx) is worth retrying with the buffer intact.
  return false;
}

void setup() {
  Serial.begin(115200);
  delay(500);
  dht.begin();
  connectWiFi();
  syncClock();
}

void loop() {
  float temperature = dht.readTemperature();
  float humidity = dht.readHumidity();

  if (isnan(temperature) || isnan(humidity)) {
    Serial.println("Sensor read failed, skipping this sample");
  } else if (bufferCount < BATCH_SIZE) {
    buffer[bufferCount++] = {temperature, humidity, time(nullptr)};
    Serial.printf("Buffered %.1f C / %.1f %% (%u/%u)\n", temperature, humidity,
                  bufferCount, BATCH_SIZE);
  } else {
    // Buffer full and still not delivered: drop the oldest rather than block.
    Serial.println("Buffer full, dropping oldest sample");
    for (uint8_t i = 1; i < BATCH_SIZE; i++) buffer[i - 1] = buffer[i];
    buffer[BATCH_SIZE - 1] = {temperature, humidity, time(nullptr)};
  }

  if (bufferCount >= BATCH_SIZE) sendBatch();

  delay(SAMPLE_INTERVAL_MS);
}
