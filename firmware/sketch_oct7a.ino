#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <DHT.h>
#include <math.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <time.h>
// ================= PIN DEFINITIONS =================
const char* WIFI_SSID = "Aizen";
const char* WIFI_PASSWORD = "air02108";

const char* API_URL =
  "http://192.168.1.7:8000/api/v1/ingestion/sensor-data";

const char* API_KEY = "dev-only-ingestion-key";

const char* DEVICE_ID = "ESP32_01";
const char* HVAC_ID = "HVAC_TEST_01";
#define DHT_PIN 5
#define DHT_TYPE DHT22

#define MQ5_PIN 34
#define ACS_PIN 35
#define PRESSURE_PIN 32
#define BUZZER_PIN 25

#define OLED_SDA 21
#define OLED_SCL 22

// ================= OLED =============================

#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64

Adafruit_SSD1306 display(
  SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, -1
);

DHT dht(DHT_PIN, DHT_TYPE);

// ================= SENSOR SETTINGS ==================

// Change this for your ACS712 variant:
// 5A = 0.185 V/A
// 20A = 0.100 V/A
// 30A = 0.066 V/A
const float ACS_SENSITIVITY = 0.100;

// Set according to your calibration.
// This is a starting value, not a universal threshold.
const int MQ5_RISE_THRESHOLD = 350;

const float TEMP_LIMIT = 35.0;
const float HUMIDITY_LIMIT = 80.0;
const float CURRENT_RISE_PERCENT = 20.0;

// PR2010 pressure sensor and voltage divider
// Assumption: 0.5-4.5 V output, pressure range 0-1 MPa
const float R_TOP = 10000.0;
const float R_BOTTOM = 20000.0;

const float SENSOR_MIN_V = 0.5;
const float SENSOR_MAX_V = 4.5;
const float PRESSURE_MAX_MPA = 1.0;

// ================= VARIABLES ========================

float temperature = NAN;
float humidity = NAN;
float current = 0.0;

float currentBaseline = 0.0;
float currentZeroVoltage = 1.65;

int mq5Raw = 0;
int mq5Baseline = 0;

// PR2010 pressure variables
float adcVoltage = 0.0;
float pressureSensorVoltage = 0.0;
float pressureMPa = 0.0;
float pressureKPa = 0.0;

bool dhtConnected = false;
bool gasRisk = false;
bool temperatureRisk = false;
bool humidityRisk = false;
bool currentRisk = false;

bool currentCalibrated = false;
bool mqCalibrated = false;

bool simulatedTest = false;
char testMode = 'N';

int page = 0;
unsigned long lastPageChange = 0;
unsigned long lastPrint = 0;

const unsigned long PAGE_TIME = 3000;
const unsigned long READ_TIME = 2000;

// ================= ACS712 ADC HELPERS ================

float readACSVoltage() {
  return analogReadMilliVolts(ACS_PIN) / 1000.0;
}

// For AC current, measure variation around the
// sampled midpoint. Verify sensitivity and calibration
// for your particular ACS712 module.
float getCurrent() {
  const int samples = 500;

  float sum = 0.0;
  float sumSquares = 0.0;

  for (int i = 0; i < samples; i++) {
    float v = readACSVoltage();

    sum += v;
    sumSquares += v * v;

    delayMicroseconds(200);
  }

  float mean = sum / samples;
  float variance =
    (sumSquares / samples) - (mean * mean);

  if (variance < 0) {
    variance = 0;
  }

  float rmsVoltage = sqrt(variance);

  return rmsVoltage / ACS_SENSITIVITY;
}

// ================= PR2010 PRESSURE SENSOR =============

void readPressure() {
  const int samples = 20;
  unsigned long totalMilliVolts = 0;

  for (int i = 0; i < samples; i++) {
    totalMilliVolts += analogReadMilliVolts(PRESSURE_PIN);
    delay(5);
  }

  // Average voltage measured at ESP32 GPIO32
  adcVoltage =
    (totalMilliVolts / (float)samples) / 1000.0;

  // Convert ADC voltage back to sensor output voltage.
  // Divider: sensor output -> 10k -> GPIO32 -> 20k -> GND
  pressureSensorVoltage =
    adcVoltage * (R_TOP + R_BOTTOM) / R_BOTTOM;

  // Convert sensor voltage to pressure.
  // Assumes 0.5 V = 0 MPa and 4.5 V = 1 MPa.
  pressureMPa =
    ((pressureSensorVoltage - SENSOR_MIN_V) /
     (SENSOR_MAX_V - SENSOR_MIN_V)) * PRESSURE_MAX_MPA;

  pressureKPa = pressureMPa * 1000.0;
}

// ================= MQ5 BASELINE =======================

void calibrateMQ5() {
  Serial.println("MQ5 baseline calibration.");
  Serial.println("Keep the area at its normal background condition.");

  long total = 0;
  const int samples = 20;

  for (int i = 0; i < samples; i++) {
    total += analogRead(MQ5_PIN);
    delay(250);
  }

  mq5Baseline = total / samples;
  mqCalibrated = true;

  Serial.print("MQ5 baseline ADC: ");
  Serial.println(mq5Baseline);

  Serial.println(
    "Tune MQ5_RISE_THRESHOLD after observing readings."
  );
}

// ================= ACS BASELINE =======================

void calibrateCurrent() {
  Serial.println("Current baseline calibration.");
  Serial.println(
    "Keep the monitored equipment at its normal operating state."
  );

  delay(1000);

  currentBaseline = getCurrent();
  currentCalibrated = true;

  Serial.print("Current baseline (A): ");
  Serial.println(currentBaseline, 2);
}

// ================= SERIAL TEST COMMANDS ===============

// Send these characters in Serial Monitor:
// N = normal
// G = simulate gas alert
// T = simulate high temperature
// H = simulate high humidity
// C = simulate high current
// X = clear simulation

void readTestCommand() {
  while (Serial.available()) {
    char c = Serial.read();

    if (c >= 'a' && c <= 'z') {
      c -= 32;
    }

    if (c == 'N' || c == 'G' || c == 'T' ||
        c == 'H' || c == 'C' || c == 'X') {

      testMode = c;
      simulatedTest = (c != 'N' && c != 'X');

      Serial.print("Test mode: ");
      Serial.println(c);
    }
  }
}
void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  Serial.print("Connecting to Wi-Fi");

  unsigned long start = millis();

  while (WiFi.status() != WL_CONNECTED &&
         millis() - start < 20000) {
    delay(500);
    Serial.print(".");
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWi-Fi connected!");
    Serial.print("ESP32 IP: ");
    Serial.println(WiFi.localIP());

    // Synchronize time for the API timestamp.
    configTime(0, 0, "pool.ntp.org", "time.google.com");
  } else {
    Serial.println("\nWi-Fi connection failed.");
  }
}

// ================= BACKEND DATA UPLOAD =================

void sendSensorData() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("Upload skipped: Wi-Fi disconnected.");
    return;
  }

  // The backend requires a valid ISO-8601 timestamp.
  time_t now = time(nullptr);
  if (now < 1700000000) {
    Serial.println("Upload skipped: waiting for NTP time sync.");
    return;
  }

  struct tm timeInfo;
  gmtime_r(&now, &timeInfo);
  char timestamp[25];
  strftime(timestamp, sizeof(timestamp), "%Y-%m-%dT%H:%M:%SZ", &timeInfo);

  HTTPClient http;
  http.setTimeout(5000);

  if (!http.begin(API_URL)) {
    Serial.println("Upload failed: could not initialize HTTP.");
    return;
  }

  StaticJsonDocument<512> doc;
  doc["device_id"] = DEVICE_ID;
  doc["hvac_id"] = HVAC_ID;
  doc["timestamp"] = timestamp;
  doc["mode"] = "normal";
  doc["event"] = getStatus();
  doc["source"] = "esp32";
  doc["schema_version"] = "1.0";

  JsonObject sensors = doc.createNestedObject("sensors");

    // MQ-5 Gas Concentration (calibrated against baseline for leak detection)
  float gasPpm = 5.0;
  if (mqCalibrated && mq5Raw > mq5Baseline) {
    gasPpm = 5.0 + ((float)(mq5Raw - mq5Baseline) * 0.8);
  }
  if (gasRisk && gasPpm < 60.0) {
    gasPpm = 180.0;
  }
  sensors["gas_ppm"] = gasPpm;
  sensors["mq5_adc"] = mq5Raw;
  doc["gas_alert"] = gasRisk;
  if (dhtConnected) {
    sensors["temperature"] = temperature;
    sensors["humidity"] = humidity;
  }
  if (isfinite(pressureKPa) && pressureKPa >= 0) {
    sensors["pressure"] = pressureKPa;
  }
  if (isfinite(current) && current >= 0) {
    sensors["compressor_current"] = current;
  }

  String requestBody;
  serializeJson(doc, requestBody);

  http.addHeader("Content-Type", "application/json");
  http.addHeader("x-api-key", API_KEY);

  Serial.println("Sending sensor data to HVAC backend...");
  int httpCode = http.POST(requestBody);

  Serial.printf("Backend HTTP status: %d\\n", httpCode);
  if (httpCode > 0) {
    Serial.println(http.getString());
  } else {
    Serial.printf("HTTP error: %s\\n", http.errorToString(httpCode).c_str());
  }

  http.end();
}

// ================= SETUP ==============================

void setup() {
  Serial.begin(115200);

  analogReadResolution(12);

  pinMode(MQ5_PIN, INPUT);
  pinMode(ACS_PIN, INPUT);

  // PR2010 pressure sensor on GPIO32
  pinMode(PRESSURE_PIN, INPUT);
  analogSetPinAttenuation(PRESSURE_PIN, ADC_11db);

  pinMode(BUZZER_PIN, OUTPUT);

  digitalWrite(BUZZER_PIN, LOW);

  Wire.begin(OLED_SDA, OLED_SCL);

  if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    Serial.println(
      "OLED NOT FOUND - check I2C wiring/address."
    );

    while (true) {
      delay(1000);
    }
  }

  dht.begin();

  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(0, 0);

  display.println("AC MONITORING");
  display.println();
  display.println("Starting sensors...");
  display.display();

  Serial.println("\nAC MONITORING PROTOTYPE");
  Serial.println("Serial Monitor: 115200 baud");
  Serial.println("Commands: N G T H C X");

  Serial.println("PR2010 pressure sensor: GPIO32");

  // MQ sensors need warm-up; readings can drift.
  // Allow warm-up according to the module datasheet
  // before treating the baseline as valid.
  delay(3000);

  calibrateMQ5();
  calibrateCurrent();

  display.clearDisplay();
  display.setCursor(0, 15);
  display.println("Calibration complete");
  display.println("Monitoring started");
  display.display();

  delay(1500);

  lastPageChange = millis();

  connectWiFi();
}

// ================= SENSOR READINGS ===================

void readSensors() {
  temperature = dht.readTemperature();
  humidity = dht.readHumidity();

  dhtConnected = !isnan(temperature) && !isnan(humidity);

  mq5Raw = analogRead(MQ5_PIN);
  current = getCurrent();

  // Read PR2010 pressure
  readPressure();

  // Actual sensor-based conditions
  gasRisk = mqCalibrated &&
            mq5Raw > mq5Baseline + MQ5_RISE_THRESHOLD;

  temperatureRisk = dhtConnected &&
                    temperature >= TEMP_LIMIT;

  humidityRisk = dhtConnected &&
                 humidity >= HUMIDITY_LIMIT;

  currentRisk = currentCalibrated &&
                currentBaseline > 0.05 &&
                current > currentBaseline *
                (1.0 + CURRENT_RISE_PERCENT / 100.0);

  // Safe software simulation for demonstration
  if (testMode == 'G') gasRisk = true;
  if (testMode == 'T') temperatureRisk = true;
  if (testMode == 'H') humidityRisk = true;
  if (testMode == 'C') currentRisk = true;

  if (testMode == 'N' || testMode == 'X') {
    // Use actual sensor-based status.
  }
}

// ================= OVERALL STATUS ====================

int riskCount() {
  return (gasRisk ? 1 : 0) +
         (temperatureRisk ? 1 : 0) +
         (humidityRisk ? 1 : 0) +
         (currentRisk ? 1 : 0);
}

const char* getStatus() {
  if (!dhtConnected) return "SENSOR ERROR";
  if (riskCount() >= 2) return "HIGH RISK";
  if (riskCount() == 1) return "WARNING";

  return "NORMAL";
}

// ================= OLED DISPLAY ======================

void updateOLED() {
  if (millis() - lastPageChange >= PAGE_TIME) {
    lastPageChange = millis();

    // Five pages: status, DHT22, gas, current, pressure
    page = (page + 1) % 5;
  }

  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(1);

  if (page == 0) {
    display.setCursor(0, 0);
    display.println("AC MONITOR - STATUS");
    display.drawLine(0, 10, 127, 10, SSD1306_WHITE);

    display.setCursor(0, 18);
    display.print("Status: ");
    display.println(getStatus());

    display.setCursor(0, 34);
    display.print("Gas: ");
    display.println(gasRisk ? "ALERT" : "NORMAL");

    display.setCursor(0, 46);
    display.print("Test: ");
    display.println(testMode);
  }

  else if (page == 1) {
    display.setCursor(0, 0);
    display.println("DHT22 ENVIRONMENT");

    display.setCursor(0, 18);
    display.print("Temperature: ");

    if (dhtConnected) {
      display.print(temperature, 1);
      display.println(" C");
    } else {
      display.println("ERROR");
    }

    display.setCursor(0, 34);
    display.print("Humidity: ");

    if (dhtConnected) {
      display.print(humidity, 1);
      display.println(" %");
    } else {
      display.println("ERROR");
    }

    display.setCursor(0, 51);
    display.println(
      temperatureRisk || humidityRisk
        ? "WARNING" : "NORMAL"
    );
  }

  else if (page == 2) {
    display.setCursor(0, 0);
    display.println("GAS SENSOR");

    display.setCursor(0, 18);
    display.print("ADC: ");
    display.println(mq5Raw);

    display.setCursor(0, 32);
    display.print("Baseline: ");
    display.println(mq5Baseline);

    display.setCursor(0, 49);
    display.println(gasRisk ? "GAS ALERT" : "NORMAL");
  }

  else if (page == 3) {
    display.setCursor(0, 0);
    display.println("ACS712 CURRENT");

    display.setCursor(0, 18);
    display.print("Current: ");
    display.print(current, 2);
    display.println(" A");

    display.setCursor(0, 32);
    display.print("Baseline: ");
    display.print(currentBaseline, 2);
    display.println(" A");

    display.setCursor(0, 49);
    display.println(currentRisk ? "WARNING" : "NORMAL");
  }

  else {
    // PR2010 PRESSURE PAGE
    display.setCursor(0, 0);
    display.println("PR2010 PRESSURE");

    display.setCursor(0, 15);
    display.print("ADC: ");
    display.print(adcVoltage, 3);
    display.println(" V");

    display.setCursor(0, 29);
    display.print("Sensor: ");
    display.print(pressureSensorVoltage, 2);
    display.println(" V");

    display.setCursor(0, 43);
    display.print("Pressure: ");
    display.print(pressureKPa, 1);
    display.println(" kPa");

    display.setCursor(0, 55);
    display.print(pressureMPa, 3);
    display.println(" MPa");
  }

  display.display();
}

// ================= SERIAL OUTPUT =====================

void printSerial() {
  Serial.println("\n------------------------------");

  if (dhtConnected) {
    Serial.printf("Temperature: %.1f C\n", temperature);
    Serial.printf("Humidity: %.1f %%\n", humidity);
  } else {
    Serial.println("DHT22: SENSOR ERROR");
  }

  Serial.printf("MQ5 ADC: %d\n", mq5Raw);
  Serial.printf("MQ5 baseline: %d\n", mq5Baseline);
  Serial.printf("Current: %.2f A\n", current);
  Serial.printf("Current baseline: %.2f A\n", currentBaseline);

  // PR2010 pressure readings
  Serial.println("--- PR2010 PRESSURE ---");

  Serial.printf("ADC voltage: %.3f V\n", adcVoltage);
  Serial.printf(
    "Sensor output: %.3f V\n",
    pressureSensorVoltage
  );
  Serial.printf("Pressure: %.2f kPa\n", pressureKPa);
  Serial.printf("Pressure: %.4f MPa\n", pressureMPa);

  Serial.printf("Gas alert: %s\n", gasRisk ? "YES" : "NO");
  Serial.printf(
    "Temperature alert: %s\n",
    temperatureRisk ? "YES" : "NO"
  );
  Serial.printf(
    "Humidity alert: %s\n",
    humidityRisk ? "YES" : "NO"
  );
  Serial.printf(
    "Current alert: %s\n",
    currentRisk ? "YES" : "NO"
  );

  Serial.print("OVERALL STATUS: ");
  Serial.println(getStatus());

  Serial.print("BUZZER: ");
  Serial.println(riskCount() > 0 ? "ON" : "OFF");

  Serial.println("------------------------------");
}

// ================= MAIN LOOP =========================

void loop() {
  readTestCommand();

  static unsigned long lastRead = 0;

  if (millis() - lastRead >= READ_TIME) {
    lastRead = millis();

    readSensors();

    // Buzzer responds to the existing risk conditions.
    digitalWrite(
      BUZZER_PIN,
      riskCount() > 0 ? HIGH : LOW
    );

    updateOLED();
    printSerial();
  } else {
    // Continue cycling through OLED pages between readings.
    updateOLED();
  }

  // Upload the latest readings every 5 seconds.
  static unsigned long lastUpload = 0;
  if (millis() - lastUpload >= 5000) {
    lastUpload = millis();
    sendSensorData();
  }
}