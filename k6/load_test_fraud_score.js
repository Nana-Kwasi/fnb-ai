/**
 * k6 Load Test — FNB-AI Fraud Scoring Endpoint
 *
 * Target: POST /api/v1/fraud/score
 * Goal:   500 TPS sustained, p99 latency < 500ms, error rate < 1%
 *
 * Run:
 *   k6 run --env BASE_URL=http://localhost:8000 \
 *          --env API_KEY=your-tenant-api-key \
 *          --env TENANT_ID=your-tenant-uuid \
 *          k6/load_test_fraud_score.js
 *
 * For a 10-minute sustained soak at 500 TPS:
 *   k6 run --env BASE_URL=http://localhost:8000 \
 *          --env API_KEY=your-tenant-api-key \
 *          --env TENANT_ID=your-tenant-uuid \
 *          --env SOAK=true \
 *          k6/load_test_fraud_score.js
 */

import http from "k6/http";
import { check, sleep } from "k6";
import { Rate, Trend } from "k6/metrics";
import { randomIntBetween } from "https://jslib.k6.io/k6-utils/1.4.0/index.js";

// ── Custom metrics ─────────────────────────────────────────────────────────────
const fraudBlockRate = new Rate("fraud_block_rate");
const fraudOtpRate   = new Rate("fraud_otp_rate");
const errorRate      = new Rate("error_rate");
const scoringLatency = new Trend("scoring_latency_ms", true);

// ── Config ────────────────────────────────────────────────────────────────────
const BASE_URL   = __ENV.BASE_URL   || "http://localhost:8000";
const API_KEY    = __ENV.API_KEY    || "test-api-key";
const TENANT_ID  = __ENV.TENANT_ID  || "00000000-0000-0000-0000-000000000001";
const SOAK_MODE  = __ENV.SOAK === "true";

// ── Scenario ──────────────────────────────────────────────────────────────────
// Ramp to 500 VUs (≈500 RPS if avg latency <1s), sustain, ramp down.
export const options = {
  scenarios: {
    fraud_score_ramp: {
      executor: "ramping-arrival-rate",
      startRate: 50,
      timeUnit: "1s",
      preAllocatedVUs: 600,
      maxVUs: 800,
      stages: SOAK_MODE
        ? [
            { duration: "2m",  target: 500 },  // ramp up
            { duration: "10m", target: 500 },  // soak
            { duration: "1m",  target: 0   },  // ramp down
          ]
        : [
            { duration: "1m",  target: 500 },  // ramp up
            { duration: "3m",  target: 500 },  // sustain
            { duration: "30s", target: 0   },  // ramp down
          ],
    },
  },

  thresholds: {
    // p99 latency must stay below 500ms (SLA target)
    "http_req_duration{scenario:fraud_score_ramp}": ["p(99)<500"],
    // p95 under 200ms (healthy target)
    "http_req_duration{scenario:fraud_score_ramp}": ["p(95)<200"],
    // Error rate under 1%
    "http_req_failed{scenario:fraud_score_ramp}": ["rate<0.01"],
    // Custom error rate metric
    "error_rate": ["rate<0.01"],
  },
};

// ── Merchant categories ───────────────────────────────────────────────────────
const MERCHANTS = [
  "GROCERY", "FUEL", "ATM_WITHDRAWAL", "ONLINE_RETAIL",
  "RESTAURANT", "PHARMACY", "ELECTRONICS", "TRAVEL",
];

const CURRENCIES = ["GHS", "NGN", "ZAR", "KES", "USD"];
const COUNTRIES  = ["GH", "NG", "ZA", "KE", "US", "GB", "CN"];
const CHANNELS   = ["mobile_app", "web", "pos", "atm"];

// ── Payload generator ─────────────────────────────────────────────────────────
function buildPayload() {
  const isSuspicious = Math.random() < 0.05; // 5% synthetic fraud-like transactions
  return {
    transaction_id:       `txn-k6-${Date.now()}-${randomIntBetween(1, 1000000)}`,
    customer_id:          `cust-${randomIntBetween(1, 50000)}`,
    amount:               isSuspicious
                            ? randomIntBetween(5000, 50000)
                            : randomIntBetween(10, 500),
    currency:             CURRENCIES[randomIntBetween(0, CURRENCIES.length - 1)],
    merchant_id:          `merch-${randomIntBetween(1, 10000)}`,
    merchant_category:    MERCHANTS[randomIntBetween(0, MERCHANTS.length - 1)],
    channel:              CHANNELS[randomIntBetween(0, CHANNELS.length - 1)],
    device_id:            isSuspicious
                            ? `dev-unknown-${randomIntBetween(1, 100)}`
                            : `dev-trusted-${randomIntBetween(1, 500)}`,
    ip_address:           isSuspicious ? "185.220.101.1" : `10.${randomIntBetween(0,255)}.${randomIntBetween(0,255)}.${randomIntBetween(1,254)}`,
    country_code:         isSuspicious
                            ? COUNTRIES[randomIntBetween(3, COUNTRIES.length - 1)]
                            : COUNTRIES[randomIntBetween(0, 2)],
    latitude:             isSuspicious ? 51.5 + Math.random() : 5.6 + Math.random() * 0.5,
    longitude:            isSuspicious ? -0.1 + Math.random() : -0.2 + Math.random() * 0.5,
    timestamp:            new Date().toISOString(),
    // Optional biometric stub
    biometrics: {
      typing_speed_wpm:   isSuspicious ? 0 : randomIntBetween(40, 120),
      touch_pressure:     isSuspicious ? 0 : 0.3 + Math.random() * 0.5,
      session_age_seconds: isSuspicious ? 3 : randomIntBetween(30, 600),
    },
  };
}

// ── Request headers ───────────────────────────────────────────────────────────
const HEADERS = {
  "Content-Type":  "application/json",
  "X-API-Key":     API_KEY,
  "X-Tenant-ID":   TENANT_ID,
  "X-Request-ID":  "",  // overwritten per request below
};

// ── Main VU function ──────────────────────────────────────────────────────────
export default function () {
  const headers = Object.assign({}, HEADERS, {
    "X-Request-ID": `k6-${Date.now()}-${randomIntBetween(1, 1000000)}`,
  });

  const payload  = JSON.stringify(buildPayload());
  const start    = Date.now();
  const response = http.post(`${BASE_URL}/api/v1/fraud/score`, payload, { headers });
  const elapsed  = Date.now() - start;
  
  scoringLatency.add(elapsed);

  const ok = check(response, {
    "status 200": (r) => r.status === 200,
    "has decision": (r) => {
      try {
        return JSON.parse(r.body).decision !== undefined;
      } catch {
        return false;
      }
    },
    "latency < 500ms": () => elapsed < 500,
  });

  errorRate.add(!ok);

  if (response.status === 200) {
    try {
      const body = JSON.parse(response.body);
      fraudBlockRate.add(body.decision === "BLOCK");
      fraudOtpRate.add(body.decision === "REQUEST_OTP");
    } catch (_) {
      // ignore parse failures — counted in error_rate
    }
  }

  // Minimal think time to stay realistic (not needed with arrival-rate executor, but kept for safety)
  // sleep(0);
}

// ── Summary hook ─────────────────────────────────────────────────────────────
export function handleSummary(data) {
  const p99 = data.metrics["http_req_duration"]?.values?.["p(99)"] ?? "N/A";
  const p95 = data.metrics["http_req_duration"]?.values?.["p(95)"] ?? "N/A";
  const rps = data.metrics["http_reqs"]?.values?.rate ?? "N/A";
  const errRate = (data.metrics["http_req_failed"]?.values?.rate ?? 0) * 100;

  console.log("─────────────────────────────────────────");
  console.log(`FNB-AI Fraud Score Load Test — Summary`);
  console.log(`  Throughput:  ${typeof rps === "number" ? rps.toFixed(1) : rps} req/s`);
  console.log(`  p95 latency: ${typeof p95 === "number" ? p95.toFixed(1) : p95} ms`);
  console.log(`  p99 latency: ${typeof p99 === "number" ? p99.toFixed(1) : p99} ms  (SLA: <500ms)`);
  console.log(`  Error rate:  ${typeof errRate === "number" ? errRate.toFixed(2) : errRate}%  (SLA: <1%)`);
  console.log("─────────────────────────────────────────");

  return {
    stdout: JSON.stringify(data.metrics, null, 2),
    "k6_load_test_results.json": JSON.stringify(data, null, 2),
  };
}
