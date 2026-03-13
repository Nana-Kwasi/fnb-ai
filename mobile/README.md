# BankAI Mobile Tester

React Native (Expo) app to test Fraud and Care APIs using your onboard API key.

## Run

```bash
cd mobile
npm install
npx expo start
```

Then press `i` for iOS simulator or `a` for Android emulator (or scan QR with Expo Go on a device).

## Setup

1. **Settings tab:** Paste your API key (from Admin onboard, e.g. `bankai_live_...`) and save.
2. **API Base URL:** Default `http://localhost:8000`.  
   - **iOS simulator:** keep localhost.  
   - **Android emulator:** use `http://10.0.2.2:8000`.  
   - **Physical device:** use your machine IP, e.g. `http://192.168.1.x:8000` (backend must be reachable).

3. **Fraud tab:** Fill transaction fields and tap "Score transaction" to call `POST /api/v1/fraud/score`.
4. **Care tab:** Fill session/customer/message and tap "Send" to call `POST /api/v1/care/chat`.

Both endpoints use the saved API key in the `X-API-Key` header.
