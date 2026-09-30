# ModelForge — Firebase Setup & Connection Guide

This guide explains how to connect your own Firebase project to ModelForge.

> [!IMPORTANT]
> **Zero-Cost & Credential Safety Guarantee**:
> - Never paste private keys or service account credentials into chat or commit them to Git.
> - ModelForge is designed to operate 100% within the **Firebase Spark Plan (Free Tier)**. No billing plan upgrade or credit card is required.

---

## 1. Firebase Project Setup

### Step 1: Create or Select a Firebase Project
1. Navigate to the [Firebase Console](https://console.firebase.google.com/).
2. Click **Add project** (or select an existing project).
3. Name your project (e.g. `modelforge-prod` or `modelforge-dev`).
4. Google Analytics is optional (can be disabled).
5. Click **Create project**. Note your **Project ID** (e.g., `modelforge-12345`).

### Step 2: Enable Firebase Authentication
1. In the Firebase Console sidebar, select **Build** -> **Authentication**.
2. Click **Get Started**.
3. Under the **Sign-in method** tab, click **Email/Password**.
4. Enable **Email/Password** and click **Save**.

### Step 3: Enable Cloud Firestore
1. In the Firebase Console sidebar, select **Build** -> **Firestore Database**.
2. Click **Create database**.
3. Choose a database location close to you (e.g., `us-central1` or `asia-south1`).
4. Select **Start in production mode** (our `firestore.rules` file will provide fine-grained security).
5. Click **Create**.

---

## 2. Generate Backend Service Account Credentials

The FastAPI backend uses the Firebase Admin SDK to verify user tokens and communicate securely with Firestore.

1. In the Firebase Console, click the gear icon (⚙️) next to *Project Overview* and choose **Project settings**.
2. Select the **Service accounts** tab.
3. Click **Generate new private key**, then confirm by clicking **Generate key**.
4. A JSON file will download to your computer (e.g. `your-project-firebase-adminsdk-xxxxx.json`).
5. **Move this file securely onto your local machine:**
   - Copy the file into your ModelForge backend folder: `backend/firebase-credentials.json`
   - *Note:* `*.json` and `*credentials*.json` are already registered in `.gitignore` to ensure they are never committed.

---

## 3. Obtain Frontend Web App Configuration

The React frontend uses the Firebase Client SDK to authenticate users directly from the browser.

1. In the Firebase Console, go to **Project settings** -> **General** tab.
2. Scroll down to the **Your apps** card and click the **Web icon** (`</>`).
3. Enter an app nickname (e.g. `ModelForge Dashboard`) and click **Register app**.
4. Firebase will display your `firebaseConfig` snippet with:
   - `apiKey`
   - `authDomain`
   - `projectId`
   - `storageBucket`
   - `messagingSenderId`
   - `appId`

---

## 4. Local Environment Configuration

### A. Backend Configuration (`backend/.env`)
Create or edit `backend/.env` using `backend/.env.example` as a template:

```bash
cd backend
cp .env.example .env
```

Set the following variables:
```env
# Set database backend to firestore
DATABASE_BACKEND=firestore

# Your Firebase Project ID
FIREBASE_PROJECT_ID=your-firebase-project-id

# Path to the service account JSON downloaded in Section 2
GOOGLE_APPLICATION_CREDENTIALS=./firebase-credentials.json

# Enable Firebase token verification on API routes
FIREBASE_AUTH_ENABLED=true
```

### B. Frontend Configuration (`frontend/.env`)
Create or edit `frontend/.env` using `frontend/.env.example` as a template:

```bash
cd frontend
cp .env.example .env
```

Populate the variables with your Web App configuration:
```env
VITE_API_BASE_URL=http://localhost:8000

VITE_FIREBASE_API_KEY=AIzaSy...
VITE_FIREBASE_AUTH_DOMAIN=your-project-id.firebaseapp.com
VITE_FIREBASE_PROJECT_ID=your-project-id
VITE_FIREBASE_STORAGE_BUCKET=your-project-id.appspot.com
VITE_FIREBASE_MESSAGING_SENDER_ID=123456789012
VITE_FIREBASE_APP_ID=1:123456789012:web:...
```

---

## 5. Verifying Connectivity

### Backend Health Check
Start the backend server:
```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

Verify Firebase connectivity via the dedicated health diagnostics endpoint:
```bash
curl http://localhost:8000/api/health/firebase
```

Expected output when properly configured:
```json
{
  "initialized": true,
  "project_id": "your-firebase-project-id",
  "credentials_path": "C:\\path\\to\\backend\\firebase-credentials.json",
  "credentials_configured": true,
  "error": null
}
```

---

## 6. Deploying Security Rules

If you have the Firebase CLI installed:
```bash
firebase login
firebase use your-firebase-project-id
firebase deploy --only firestore:rules
```

Alternatively, you can copy the contents of [firestore.rules](file:///c:/college/ModelForge-Phase5-source/firestore.rules) and paste them directly into the **Firestore Database -> Rules** tab in the Firebase Console and click **Publish**.
