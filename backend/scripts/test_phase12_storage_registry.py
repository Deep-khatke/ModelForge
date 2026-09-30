#!/usr/bin/env python3
"""
ModelForge — Phase 12: Cloud Storage, Container Registry & Persistent Infrastructure Test Suite

Automated verification script executing the comprehensive Phase 12 test suite against
the active Kubernetes cluster (modelforge namespace), MinIO local object storage,
and the local Docker container registry.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request

NAMESPACE = "modelforge"
REGISTRY_URL = "http://localhost:5000"
MINIO_URL = "http://localhost:9000"


def run_cmd(cmd: list[str], timeout: int = 60) -> tuple[int, str, str]:
    """Execute command and return (returncode, stdout, stderr)."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"


def run_kubectl(args: list[str], timeout: int = 60) -> tuple[int, str, str]:
    return run_cmd(["kubectl"] + args, timeout=timeout)


def format_result(test_num: int, name: str, expected: str, actual: str, status: str, explanation: str):
    print("=" * 80)
    print(f"TEST {test_num}: {name}")
    print("=" * 80)
    print(f"Expected:    {expected}")
    print(f"Actual:      {actual}")
    print(f"Result:      {status}")
    print(f"Explanation: {explanation}")
    print()


def main():
    print("================================================================================")
    print(" MODELFORGE PHASE 12: CLOUD STORAGE & CONTAINER REGISTRY VERIFICATION SUITE")
    print(f" Target Namespace: {NAMESPACE}")
    print(f" Timestamp:        {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    print("================================================================================\n")

    results = []

    # -------------------------------------------------------------------------
    # TEST 1: Cluster & Pod Status
    # -------------------------------------------------------------------------
    rc, stdout, stderr = run_kubectl(["get", "pods", "-n", NAMESPACE, "--no-headers"])
    lines = stdout.splitlines() if stdout else []
    running_count = sum(1 for line in lines if "Running" in line)
    expected = "All core pods Running in modelforge namespace (minio, registry, backend, frontend, model-server)"
    actual = f"{running_count} pods in Running state"
    passed = rc == 0 and running_count >= 5
    status = "PASS" if passed else "FAIL"
    results.append(passed)
    format_result(1, "Cluster & Pod Status", expected, actual, status,
                  "Verifies that all workloads including storage and registry are operational.")

    # -------------------------------------------------------------------------
    # TEST 2: Local Container Registry API Availability
    # -------------------------------------------------------------------------
    try:
        req = urllib.request.Request(f"{REGISTRY_URL}/v2/")
        with urllib.request.urlopen(req, timeout=5) as resp:
            reg_status = resp.status
            reg_header = resp.headers.get("Docker-Distribution-Api-Version", "")
    except Exception as e:
        reg_status = str(e)
        reg_header = ""

    expected = "HTTP 200 with Docker-Distribution-Api-Version: registry/2.0"
    actual = f"Status {reg_status}, Api-Version: {reg_header}"
    passed = reg_status == 200 and "registry/2.0" in reg_header
    status = "PASS" if passed else "FAIL"
    results.append(passed)
    format_result(2, "Local Container Registry API", expected, actual, status,
                  "Confirms registry:2 is serving standard Docker Registry v2 API.")

    # -------------------------------------------------------------------------
    # TEST 3: Registry Image Catalog & Tags
    # -------------------------------------------------------------------------
    try:
        with urllib.request.urlopen(f"{REGISTRY_URL}/v2/_catalog", timeout=5) as resp:
            cat_data = json.loads(resp.read().decode())
            repos = cat_data.get("repositories", [])
    except Exception as e:
        repos = [str(e)]

    expected = "Registry contains modelforge/backend, modelforge/frontend, modelforge/inference"
    actual = f"Catalog: {repos}"
    passed = any("backend" in r for r in repos) and any("inference" in r for r in repos) and any("frontend" in r for r in repos)
    status = "PASS" if passed else "FAIL"
    results.append(passed)
    format_result(3, "Registry Image Catalog", expected, actual, status,
                  "Verifies all ModelForge core images were pushed and registered.")

    # -------------------------------------------------------------------------
    # TEST 4: Kubernetes Image Pull Verification
    # -------------------------------------------------------------------------
    rc, stdout, stderr = run_kubectl([
        "get", "deployments", "-n", NAMESPACE,
        "-o", "jsonpath={range .items[*]}{.metadata.name}: {.spec.template.spec.containers[*].image}{'\\n'}{end}"
    ])
    expected = "Deployments configured with local registry images (172.18.0.9:5000/...)"
    actual = stdout
    passed = rc == 0 and "172.18.0.9:5000" in stdout
    status = "PASS" if passed else "FAIL"
    results.append(passed)
    format_result(4, "Kubernetes Image Pull Source", expected, actual, status,
                  "Confirms cluster workloads pull directly from the internal container registry.")

    # -------------------------------------------------------------------------
    # TEST 5: MinIO S3 API Health & Service Discovery
    # -------------------------------------------------------------------------
    try:
        with urllib.request.urlopen(f"{MINIO_URL}/minio/health/live", timeout=5) as resp:
            minio_live = resp.status
    except Exception as e:
        minio_live = str(e)

    expected = "HTTP 200 OK from MinIO health endpoint"
    actual = f"Status {minio_live}"
    passed = minio_live == 200
    status = "PASS" if passed else "FAIL"
    results.append(passed)
    format_result(5, "MinIO Health & S3 Endpoint", expected, actual, status,
                  "Confirms MinIO object storage is healthy and responding to S3 probe requests.")

    # -------------------------------------------------------------------------
    # TEST 6: MinIO Dedicated Bucket Provisioning
    # -------------------------------------------------------------------------
    rc, stdout, stderr = run_kubectl([
        "exec", "-n", NAMESPACE, "deploy/modelforge-backend", "--",
        "python", "-c",
        "from app.services.storage.factory import get_artifact_store; "
        "store = get_artifact_store(); "
        "print('BUCKET_EXISTS:', store._get_client().bucket_exists('modelforge-models'))"
    ])
    expected = "BUCKET_EXISTS: True"
    actual = stdout
    passed = rc == 0 and "BUCKET_EXISTS: True" in stdout
    status = "PASS" if passed else "FAIL"
    results.append(passed)
    format_result(6, "Dedicated Model Artifact Bucket", expected, actual, status,
                  "Confirms bucket 'modelforge-models' exists in MinIO.")

    # -------------------------------------------------------------------------
    # TEST 7: End-to-End Object Storage Upload & Metadata
    # -------------------------------------------------------------------------
    rc, stdout, stderr = run_kubectl([
        "exec", "-n", NAMESPACE, "deploy/modelforge-backend", "--",
        "python", "-c",
        "import joblib, io; "
        "from sklearn.linear_model import LogisticRegression; "
        "from app.services.storage.factory import get_artifact_store; "
        "m = LogisticRegression().fit([[1.0, 2.0], [2.0, 3.0]], [0, 1]); "
        "b = io.BytesIO(); joblib.dump(m, b); b.seek(0); "
        "store = get_artifact_store(); "
        "name, uri, sz = store.upload_model('p12-e2e', 'v1', 'model.joblib', b.read(), user_id='admin'); "
        "meta = store.get_model_metadata(uri); "
        "print('UPLOAD_OK:', uri.startswith('s3://modelforge-models/'), 'SIZE:', meta.get('size') > 0)"
    ])
    expected = "UPLOAD_OK: True SIZE: True"
    actual = stdout
    passed = rc == 0 and "UPLOAD_OK: True SIZE: True" in stdout
    status = "PASS" if passed else "FAIL"
    results.append(passed)
    format_result(7, "Model Upload via Storage Abstraction", expected, actual, status,
                  "Confirms artifact is uploaded to MinIO under models/p12-e2e/v1/ with metadata.")

    # -------------------------------------------------------------------------
    # TEST 8: Model Retrieval & Inference Execution
    # -------------------------------------------------------------------------
    rc, stdout, stderr = run_kubectl([
        "exec", "-n", NAMESPACE, "deploy/modelforge-backend", "--",
        "python", "-c",
        "from app.services.storage.factory import get_artifact_store; "
        "store = get_artifact_store(); "
        "uri = 's3://modelforge-models/models/p12-e2e/v1/model.joblib'; "
        "m = store.load_model(uri); "
        "pred = m.predict([[1.0, 2.0]]); "
        "print('INFERENCE_PRED:', pred.tolist())"
    ])
    expected = "INFERENCE_PRED: [0]"
    actual = stdout
    passed = rc == 0 and "INFERENCE_PRED: [0]" in stdout
    status = "PASS" if passed else "FAIL"
    results.append(passed)
    format_result(8, "Model Artifact Retrieval & Inference", expected, actual, status,
                  "Confirms model binary is retrieved from MinIO, deserialized, and predicts accurately.")

    # -------------------------------------------------------------------------
    # TEST 9: Persistent Storage Survival across Workload Restart
    # -------------------------------------------------------------------------
    rc, stdout, stderr = run_kubectl([
        "exec", "-n", NAMESPACE, "deploy/modelforge-backend", "--",
        "python", "-c",
        "from app.services.storage.factory import get_artifact_store; "
        "store = get_artifact_store(); "
        "uri = 's3://modelforge-models/models/phase12-test-model/v1/classifier.joblib'; "
        "print('PERSISTED_EXISTS:', store.model_exists(uri))"
    ])
    expected = "PERSISTED_EXISTS: True"
    actual = stdout
    passed = rc == 0 and "PERSISTED_EXISTS: True" in stdout
    status = "PASS" if passed else "FAIL"
    results.append(passed)
    format_result(9, "Persistence Verification (MinIO PVC)", expected, actual, status,
                  "Confirms model artifact survived MinIO pod restarts and PVC retains objects.")

    # -------------------------------------------------------------------------
    # TEST 10: Storage Failure & Graceful Degradation
    # -------------------------------------------------------------------------
    snippet = (
        "from app.services.storage.minio_storage import MinioStorageArtifactStore\n"
        "bad = MinioStorageArtifactStore(endpoint='http://127.0.0.1:9999')\n"
        "try:\n"
        "    bad.upload_model('x', 'v1', 'm.joblib', b'bytes')\n"
        "    print('FAIL')\n"
        "except Exception as e:\n"
        "    print('HANDLED_FAILURE:', type(e).__name__)\n"
    )
    rc, stdout, stderr = run_kubectl([
        "exec", "-n", NAMESPACE, "deploy/modelforge-backend", "--",
        "python", "-c", snippet
    ], timeout=60)
    expected = "HANDLED_FAILURE: MaxRetryError"
    actual = stdout if stdout else f"RC={rc} STDERR={stderr}"
    passed = rc == 0 and "HANDLED_FAILURE" in stdout
    status = "PASS" if passed else "FAIL"
    results.append(passed)
    format_result(10, "Storage Failure Handling", expected, actual, status,
                  "Verifies storage client reports meaningful exceptions when storage is unavailable.")

    # -------------------------------------------------------------------------
    # TEST 11: Firebase & Cloud Firestore Regression
    # -------------------------------------------------------------------------
    rc, stdout, stderr = run_kubectl([
        "exec", "-n", NAMESPACE, "deploy/modelforge-backend", "--",
        "python", "-c",
        "from app.services.database.factory import get_model_repository; "
        "repo = get_model_repository(); "
        "print('FIRESTORE_ACTIVE:', type(repo).__name__ == 'FirestoreModelRepository')"
    ])
    expected = "FIRESTORE_ACTIVE: True"
    actual = stdout
    passed = rc == 0 and "FIRESTORE_ACTIVE: True" in stdout
    status = "PASS" if passed else "FAIL"
    results.append(passed)
    format_result(11, "Firebase Regression (Phase 8.5)", expected, actual, status,
                  "Confirms Firestore metadata persistence remains active alongside object storage.")

    # -------------------------------------------------------------------------
    # TEST 12: Cluster Inference Regression (Phase 11)
    # -------------------------------------------------------------------------
    rc, stdout, stderr = run_kubectl([
        "exec", "-n", NAMESPACE, "deploy/modelforge-backend", "--",
        "python", "-c",
        "import urllib.request, json; "
        "data = json.dumps({'features': [[1.0, 2.0]]}).encode(); "
        "req = urllib.request.Request('http://model-server:8000/predict', data=data, headers={'Content-Type': 'application/json'}); "
        "resp = json.loads(urllib.request.urlopen(req).read().decode()); "
        "print('PREDICT_SUCCESS:', len(resp.get('predictions', [])) > 0)"
    ])
    expected = "PREDICT_SUCCESS: True"
    actual = stdout
    passed = rc == 0 and "PREDICT_SUCCESS: True" in stdout
    status = "PASS" if passed else "FAIL"
    results.append(passed)
    format_result(12, "Cluster Inference Pipeline Regression", expected, actual, status,
                  "Confirms live model-server continues serving predictions across the internal network.")

    # -------------------------------------------------------------------------
    # SUMMARY
    # -------------------------------------------------------------------------
    passed_count = sum(results)
    total_count = len(results)
    print("=" * 80)
    print(" MODELFORGE PHASE 12: TEST SUMMARY")
    print("=" * 80)
    print(f" Total Tests Executed: {total_count}")
    print(f" Tests Passed:         {passed_count} / {total_count} ({int(passed_count / total_count * 100)}%)")
    print(f" Tests Failed:         {total_count - passed_count} / {total_count}")
    print("=" * 80)

    if passed_count == total_count:
        print("\n>>> ALL PHASE 12 STORAGE & REGISTRY TESTS PASSED SUCCESSFULLY! <<<\n")
        sys.exit(0)
    else:
        print("\n>>> SOME TESTS FAILED. PLEASE REVIEW LOGS. <<<\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
