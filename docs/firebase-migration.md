# ModelForge — Database Migration Guide (SQLite to Firestore)

This document describes how to execute and validate the migration of existing ModelForge SQLite data into Google Cloud Firestore.

---

## 1. Overview & Safety Guarantees

The ModelForge migration script ([backend/scripts/migrate_sqlite_to_firebase.py](file:///c:/college/ModelForge-Phase5-source/backend/scripts/migrate_sqlite_to_firebase.py)) is designed with strict safety principles:

1. **Non-Destructive:** The source SQLite database (`modelforge.db`) is read-only during migration. It is never modified or deleted.
2. **Idempotent:** Every record checks document existence before writing. If a model, version, deployment, or user already exists in Firestore, it is skipped without error.
3. **Dry-Run Preview:** Supports `--dry-run` to preview the migration before writing any data to Cloud Firestore.
4. **Preserved Identifiers:** Primary keys (`id`), version tags (`v1`, `v2`), foreign key relationships, and UTC timestamps are preserved across all records.
5. **Separation of Passwords:** User passwords and bcrypt hashes are **not** migrated into Firestore documents. User identity is managed directly by Firebase Authentication.

---

## 2. Pre-requisites

1. Firebase project created with Firestore enabled (see [docs/firebase-setup.md](file:///c:/college/ModelForge-Phase5-source/docs/firebase-setup.md)).
2. Backend `.env` configured with:
   ```env
   FIREBASE_PROJECT_ID=your-project-id
   GOOGLE_APPLICATION_CREDENTIALS=./firebase-credentials.json
   ```

---

## 3. Running the Migration

### Step 1: Dry-Run (Safe Preview)
Simulate the migration to verify records and relationships without writing to Firestore:

```bash
cd backend
python scripts/migrate_sqlite_to_firebase.py --dry-run
```

Example dry-run output:
```text
============================================================
  ModelForge Phase 8.5: SQLite -> Firebase Migration
============================================================
[INFO] Source SQLite Database: sqlite:///./modelforge.db
[INFO] Mode: DRY-RUN (Preview)
[INFO] Found 3 user records in SQLite.
[INFO] Migrated user: admin@modelforge.local (role: ADMIN)
[INFO] Found 2 model records in SQLite.
[INFO] Migrated model: fraud_detector (abc123def456)
[INFO]   -> Migrated version v1 for model 'fraud_detector'
[INFO]   -> Migrated version v2 for model 'fraud_detector'
============================================================
  DRY RUN COMPLETE (No Firestore changes written)
============================================================
Total records processed: 6
Successfully migrated:   6
Skipped (already exist): 0
Failed / Errors:         0
------------------------------------------------------------
Breakdown by entity:
  * Users               : created=3    skipped=0    failed=0   
  * Models              : created=1    skipped=0    failed=0   
  * ModelVersions       : created=2    skipped=0    failed=0   
============================================================
```

### Step 2: Live Migration
Execute the live migration to write records to Firestore:

```bash
python scripts/migrate_sqlite_to_firebase.py
```

### Optional Flags
- `--overwrite`: Force updates on documents that already exist in Firestore (default is to skip existing).
- `--sqlite-url <URL>`: Override the source database URL (e.g. `sqlite:///./backup.db`).

---

## 4. Verification Checklist

After running the migration:
1. Open the [Firebase Console](https://console.firebase.google.com/) -> **Firestore Database**.
2. Verify the following collections exist:
   - `users`: Contains user profiles with roles (`ADMIN`, `OPERATOR`, `VIEWER`).
   - `models`: Contains registered model documents.
   - `models/{id}/versions`: Contains version records under each model.
   - `deployments`: Contains deployment records.
   - `deployments/{id}/replicas`: Contains replica state records.
   - `audit_events`: Contains audit logs.
3. Switch backend `.env` to `DATABASE_BACKEND=firestore` and start the backend:
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```
4. Check that existing models and deployments load in the frontend dashboard.

---

## 5. SQLite Decommissioning Instructions

> [!CAUTION]
> Do NOT delete SQLite immediately after migration!

Follow this safe decommissioning procedure:
1. **Retain SQLite Backup:** Keep `modelforge.db` intact in your repository or archive it as `modelforge.db.bak`.
2. **Verify All Workflows:**
   - Model upload (`/api/v1/models/upload`)
   - Model retrieval & listing (`/api/v1/models`)
   - Deployment creation (`/api/v1/deployments`)
   - Inference execution (`/api/v1/models/{id}/predict`)
   - Monitoring metrics (`/api/v1/monitoring/summary`)
3. **Archive SQLite:** Once all verification tests pass, move the SQLite database to a safe archive directory outside the running deployment path.
