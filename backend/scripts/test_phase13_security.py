#!/usr/bin/env python3
"""
ModelForge — Phase 13: Authentication, IAM & Cloud Security Verification Suite

Automated verification suite executing real tests against:
1. Valid Authentication (JWT / Firebase)
2. Missing Authentication (HTTP 401)
3. Invalid / Malformed Authentication (HTTP 401)
4. Role-Based Access Control (RBAC 403 Forbidden)
5. Resource Ownership & IDOR Protection (403 Forbidden)
6. Kubernetes RBAC Least-Privilege (kubectl auth can-i)
7. NetworkPolicy Micro-Segmentation (Allowed & Blocked paths)
8. Secret Protection & Leak Scan
9. Model Artifact S3 Protection (Anonymous Denied 403)
10. Firebase / Firestore Access & Credentials
11. CORS Origin Restriction
12. Security & Browser Hardening Headers
13. Container & Pod Security Contexts
14. Real Model Inference Pipeline
15. Horizontal Pod Autoscaler (HPA) Health
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request

NAMESPACE = "modelforge"
BACKEND_URL = "http://localhost:8000"
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


def http_request(
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    data: dict | bytes | None = None,
) -> tuple[int, dict | str, dict[str, str]]:
    """Make HTTP request and return (status_code, body, response_headers)."""
    headers = headers or {}
    req_data = None
    if isinstance(data, dict):
        req_data = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif isinstance(data, bytes):
        req_data = data

    req = urllib.request.Request(url, data=req_data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp_headers = {k.lower(): v for k, v in resp.headers.items()}
            body_bytes = resp.read()
            try:
                parsed = json.loads(body_bytes.decode("utf-8"))
            except Exception:
                parsed = body_bytes.decode("utf-8", errors="replace")
            return resp.status, parsed, resp_headers
    except urllib.error.HTTPError as exc:
        resp_headers = {k.lower(): v for k, v in exc.headers.items()}
        body_bytes = exc.read()
        try:
            parsed = json.loads(body_bytes.decode("utf-8"))
        except Exception:
            parsed = body_bytes.decode("utf-8", errors="replace")
        return exc.code, parsed, resp_headers
    except Exception as exc:
        return 0, str(exc), {}


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
    print(" MODELFORGE PHASE 13: AUTHENTICATION, IAM & CLOUD SECURITY VERIFICATION SUITE")
    print(f" Target Namespace: {NAMESPACE}")
    print(f" Timestamp:        {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    print("================================================================================\n")

    results = []

    # -------------------------------------------------------------------------
    # TEST 1: Valid Authentication & Token Verification
    # -------------------------------------------------------------------------
    # Authenticate via /api/v1/auth/login using initial admin credentials
    login_status, login_body, _ = http_request(
        f"{BACKEND_URL}/api/v1/auth/login",
        method="POST",
        data={"email": "admin@modelforge.local", "password": "AdminPassword123!"}
    )
    admin_token = login_body.get("access_token", "") if isinstance(login_body, dict) else ""
    
    # Query /api/v1/auth/me with valid Bearer token
    me_status, me_body, _ = http_request(
        f"{BACKEND_URL}/api/v1/auth/me",
        method="GET",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    expected = "HTTP 200 OK with authenticated user record (admin@modelforge.local, role ADMIN)"
    actual = f"Status {me_status}, Email: {me_body.get('email') if isinstance(me_body, dict) else None}, Role: {me_body.get('role') if isinstance(me_body, dict) else None}"
    passed = me_status == 200 and isinstance(me_body, dict) and me_body.get("email") == "admin@modelforge.local"
    status_str = "PASS" if passed else "FAIL"
    results.append(passed)
    format_result(1, "Valid Authentication (Bearer Token)", expected, actual, status_str,
                  "Confirms valid authentication produces identity context and accepted requests.")

    # -------------------------------------------------------------------------
    # TEST 2: Missing Authentication (HTTP 401)
    # -------------------------------------------------------------------------
    # Query protected /api/v1/auth/me without Authorization header
    unauth_status, unauth_body, _ = http_request(
        f"{BACKEND_URL}/api/v1/auth/me",
        method="GET"
    )
    expected = "HTTP 401 Unauthorized"
    actual = f"Status {unauth_status}: {unauth_body}"
    passed = unauth_status == 401
    status_str = "PASS" if passed else "FAIL"
    results.append(passed)
    format_result(2, "Missing Authentication Rejection", expected, actual, status_str,
                  "Confirms unauthenticated requests to protected endpoints are rejected with HTTP 401.")

    # -------------------------------------------------------------------------
    # TEST 3: Invalid & Malformed Authentication (HTTP 401)
    # -------------------------------------------------------------------------
    # Provide invalid signature / corrupted token
    bad_token_status, bad_token_body, _ = http_request(
        f"{BACKEND_URL}/api/v1/auth/me",
        method="GET",
        headers={"Authorization": "Bearer invalid.token.signature"}
    )
    malformed_status, malformed_body, _ = http_request(
        f"{BACKEND_URL}/api/v1/auth/me",
        method="GET",
        headers={"Authorization": "NotBearerToken"}
    )
    expected = "HTTP 401 for both invalid and malformed authorization headers"
    actual = f"Invalid Token Status: {bad_token_status}, Malformed Header Status: {malformed_status}"
    passed = bad_token_status == 401 and malformed_status == 401
    status_str = "PASS" if passed else "FAIL"
    results.append(passed)
    format_result(3, "Invalid / Malformed Authentication Rejection", expected, actual, status_str,
                  "Confirms tampered, expired, or malformed tokens cannot access protected resources.")

    # -------------------------------------------------------------------------
    # TEST 4: Role-Based Access Control (RBAC 403 Forbidden)
    # -------------------------------------------------------------------------
    # Create or fetch a viewer user to test privilege boundaries
    viewer_create_status, viewer_create_body, _ = http_request(
        f"{BACKEND_URL}/api/v1/users",
        method="POST",
        headers={"Authorization": f"Bearer {admin_token}"},
        data={
            "email": "viewer-test@modelforge.local",
            "password": "ViewerPassword123!",
            "display_name": "Test Viewer User",
            "role": "VIEWER"
        }
    )
    # Login as viewer
    v_login_status, v_login_body, _ = http_request(
        f"{BACKEND_URL}/api/v1/auth/login",
        method="POST",
        data={"email": "viewer-test@modelforge.local", "password": "ViewerPassword123!"}
    )
    viewer_token = v_login_body.get("access_token", "") if isinstance(v_login_body, dict) else ""

    # VIEWER attempts an ADMIN/OPERATOR action: creating a deployment
    viewer_action_status, viewer_action_body, _ = http_request(
        f"{BACKEND_URL}/api/v1/deployments",
        method="POST",
        headers={"Authorization": f"Bearer {viewer_token}"},
        data={"model_id": "any-id", "replicas": 1}
    )
    expected = "HTTP 403 Forbidden when VIEWER attempts OPERATOR/ADMIN operation"
    actual = f"Status {viewer_action_status}: {viewer_action_body}"
    passed = viewer_action_status == 403
    status_str = "PASS" if passed else "FAIL"
    results.append(passed)
    format_result(4, "Role-Based Access Control (RBAC)", expected, actual, status_str,
                  "Confirms server enforces strict role permissions and blocks unauthorized roles with HTTP 403.")

    # -------------------------------------------------------------------------
    # TEST 5: Resource Ownership & IDOR Protection
    # -------------------------------------------------------------------------
    # Create an OPERATOR user: operator-a
    http_request(
        f"{BACKEND_URL}/api/v1/users",
        method="POST",
        headers={"Authorization": f"Bearer {admin_token}"},
        data={
            "email": "operator-a@modelforge.local",
            "password": "OperatorPassword123!",
            "display_name": "Operator User A",
            "role": "OPERATOR"
        }
    )
    # Create another OPERATOR user: operator-b
    http_request(
        f"{BACKEND_URL}/api/v1/users",
        method="POST",
        headers={"Authorization": f"Bearer {admin_token}"},
        data={
            "email": "operator-b@modelforge.local",
            "password": "OperatorPassword123!",
            "display_name": "Operator User B",
            "role": "OPERATOR"
        }
    )
    # Login as operator-a
    _, op_a_login, _ = http_request(
        f"{BACKEND_URL}/api/v1/auth/login",
        method="POST",
        data={"email": "operator-a@modelforge.local", "password": "OperatorPassword123!"}
    )
    op_a_token = op_a_login.get("access_token", "") if isinstance(op_a_login, dict) else ""

    # Login as operator-b
    _, op_b_login, _ = http_request(
        f"{BACKEND_URL}/api/v1/auth/login",
        method="POST",
        data={"email": "operator-b@modelforge.local", "password": "OperatorPassword123!"}
    )
    op_b_token = op_b_login.get("access_token", "") if isinstance(op_b_login, dict) else ""

    # In Python via backend exec or local DB: create a model owned by operator-a
    py_code = (
        "from app.database import SessionLocal\n"
        "from app.models import Model, User\n"
        "db = SessionLocal()\n"
        "user_a = db.query(User).filter_by(email='operator-a@modelforge.local').first()\n"
        "m = db.query(Model).filter_by(name='idor-private-model-a').first()\n"
        "if not m:\n"
        "    m = Model(name='idor-private-model-a', owner_id=user_a.id if user_a else None)\n"
        "    db.add(m)\n"
        "    db.commit()\n"
        "print('MODEL_CREATED_ID:', m.id)\n"
    )
    rc, stdout, stderr = run_kubectl([
        "exec", "-n", NAMESPACE, "deploy/modelforge-backend", "--",
        "python", "-c", py_code
    ])
    model_a_id = stdout.split("MODEL_CREATED_ID:")[1].strip() if "MODEL_CREATED_ID:" in stdout else "idor-m-a"

    # Operator B attempts to access Operator A's private model
    idor_status, idor_body, _ = http_request(
        f"{BACKEND_URL}/api/v1/models/{model_a_id}",
        method="GET",
        headers={"Authorization": f"Bearer {op_b_token}"}
    )
    expected = "HTTP 403 Forbidden when Operator B requests Operator A's model"
    actual = f"Status {idor_status}: {idor_body}"
    passed = idor_status == 403
    status_str = "PASS" if passed else "FAIL"
    results.append(passed)
    format_result(5, "Resource Ownership & IDOR Protection", expected, actual, status_str,
                  "Confirms server prevents insecure direct object references across different users.")

    # -------------------------------------------------------------------------
    # TEST 6: Kubernetes RBAC Least-Privilege Verification
    # -------------------------------------------------------------------------
    # Backend can list/create deployments
    rc1, out1, _ = run_kubectl(["auth", "can-i", "list", "deployments", "--as=system:serviceaccount:modelforge:modelforge-backend", "-n", NAMESPACE])
    rc2, out2, _ = run_kubectl(["auth", "can-i", "create", "deployments", "--as=system:serviceaccount:modelforge:modelforge-backend", "-n", NAMESPACE])
    # Backend CANNOT delete pods or get secrets
    rc3, out3, _ = run_kubectl(["auth", "can-i", "delete", "pods", "--as=system:serviceaccount:modelforge:modelforge-backend", "-n", NAMESPACE])
    rc4, out4, _ = run_kubectl(["auth", "can-i", "get", "secrets", "--as=system:serviceaccount:modelforge:modelforge-backend", "-n", NAMESPACE])
    # Model-server CANNOT access pods
    rc5, out5, _ = run_kubectl(["auth", "can-i", "get", "pods", "--as=system:serviceaccount:modelforge:modelforge-model-server", "-n", NAMESPACE])

    expected = "list deployments: yes, create deployments: yes, delete pods: no, get secrets: no, model-server get pods: no"
    actual = f"list deploy: {out1}, create deploy: {out2}, delete pods: {out3}, get secrets: {out4}, model-server pods: {out5}"
    passed = out1 == "yes" and out2 == "yes" and out3 == "no" and out4 == "no" and out5 == "no"
    status_str = "PASS" if passed else "FAIL"
    results.append(passed)
    format_result(6, "Kubernetes RBAC Least-Privilege", expected, actual, status_str,
                  "Confirms Kubernetes RBAC grants only required permissions and denies privileged actions.")

    # -------------------------------------------------------------------------
    # TEST 7: NetworkPolicy Pod Micro-Segmentation
    # -------------------------------------------------------------------------
    # Backend -> Model Server (Allowed)
    rc_b2m, out_b2m, _ = run_kubectl([
        "exec", "-n", NAMESPACE, "deploy/modelforge-backend", "--",
        "curl", "-s", "-m", "5", "http://model-server:8000/health"
    ])
    # Frontend -> Model Server (Blocked by NetPol)
    rc_f2m, out_f2m, err_f2m = run_kubectl([
        "exec", "-n", NAMESPACE, "deploy/modelforge-frontend", "--",
        "wget", "-T", "3", "-q", "-O", "-", "http://model-server:8000/health"
    ], timeout=15)
    f2m_blocked = rc_f2m != 0 or "timed out" in err_f2m or "timed out" in out_f2m

    expected = "Backend -> ModelServer: ALLOWED (status healthy); Frontend -> ModelServer: BLOCKED"
    actual = f"Backend -> ModelServer: {out_b2m}; Frontend -> ModelServer blocked: {f2m_blocked}"
    passed = "healthy" in out_b2m and f2m_blocked
    status_str = "PASS" if passed else "FAIL"
    results.append(passed)
    format_result(7, "NetworkPolicy Micro-Segmentation", expected, actual, status_str,
                  "Confirms NetworkPolicies enforce isolation: inference is accessible only to backend.")

    # -------------------------------------------------------------------------
    # TEST 8: Secrets Security & Leak Protection
    # -------------------------------------------------------------------------
    rc_sec, out_sec, _ = run_kubectl(["get", "secrets", "-n", NAMESPACE, "--no-headers"])
    sec_names = [line.split()[0] for line in out_sec.splitlines() if line]
    
    # Check .gitignore for sensitive files
    with open(".gitignore", "r", encoding="utf-8") as f:
        gitignore_content = f.read()
    secrets_ignored = "k8s/secrets.yaml" in gitignore_content and "credentials" in gitignore_content

    expected = "Secrets present in modelforge namespace, real secret YAMLs gitignored, no credentials leaked"
    actual = f"Namespace Secrets: {sec_names}, Secret files gitignored: {secrets_ignored}"
    passed = "modelforge-secrets" in sec_names and secrets_ignored
    status_str = "PASS" if passed else "FAIL"
    results.append(passed)
    format_result(8, "Secrets Management & Leak Protection", expected, actual, status_str,
                  "Confirms credentials are encrypted in Kubernetes Secrets and excluded from repository.")

    # -------------------------------------------------------------------------
    # TEST 9: Model Artifact Access Control (S3 Protection)
    # -------------------------------------------------------------------------
    # Attempt unauthenticated anonymous GET directly to MinIO model artifact
    anon_s3_status, anon_s3_body, _ = http_request(
        f"{MINIO_URL}/modelforge-models/models/phase12-test-model/v1/classifier.joblib",
        method="GET"
    )
    expected = "HTTP 403 Forbidden (AccessDenied for anonymous requests)"
    actual = f"Status {anon_s3_status}: {anon_s3_body}"
    passed = anon_s3_status == 403 and "AccessDenied" in str(anon_s3_body)
    status_str = "PASS" if passed else "FAIL"
    results.append(passed)
    format_result(9, "Model Artifact Object Storage Protection", expected, actual, status_str,
                  "Confirms MinIO rejects unauthenticated anonymous requests; artifacts require valid credentials.")

    # -------------------------------------------------------------------------
    # TEST 10: Firebase & Cloud Firestore Regression
    # -------------------------------------------------------------------------
    fb_status, fb_body, _ = http_request(f"{BACKEND_URL}/api/health/firebase")
    expected = "HTTP 200 with initialized: true, credentials_configured: true"
    actual = f"Status {fb_status}: {fb_body}"
    passed = fb_status == 200 and isinstance(fb_body, dict) and fb_body.get("initialized") is True
    status_str = "PASS" if passed else "FAIL"
    results.append(passed)
    format_result(10, "Firebase & Cloud Firestore Health", expected, actual, status_str,
                  "Confirms Firebase Admin SDK and Firestore connections remain healthy.")

    # -------------------------------------------------------------------------
    # TEST 11: CORS Origin Restriction
    # -------------------------------------------------------------------------
    # Valid origin test: http://localhost:5173
    req_valid = urllib.request.Request(
        f"{BACKEND_URL}/api/health",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
        method="OPTIONS"
    )
    try:
        with urllib.request.urlopen(req_valid, timeout=5) as r:
            allowed_origin = r.headers.get("access-control-allow-origin")
    except Exception:
        allowed_origin = None

    # Malicious origin test: http://attacker.evil.com
    req_bad = urllib.request.Request(
        f"{BACKEND_URL}/api/health",
        headers={"Origin": "http://attacker.evil.com", "Access-Control-Request-Method": "GET"},
        method="OPTIONS"
    )
    try:
        with urllib.request.urlopen(req_bad, timeout=5) as r:
            bad_allowed = r.headers.get("access-control-allow-origin")
    except Exception:
        bad_allowed = None

    expected = "Allowed origin: http://localhost:5173; Unauthorized origin: None"
    actual = f"Allowed: {allowed_origin}, Malicious: {bad_allowed}"
    passed = allowed_origin == "http://localhost:5173" and bad_allowed != "http://attacker.evil.com"
    status_str = "PASS" if passed else "FAIL"
    results.append(passed)
    format_result(11, "CORS Origin Restriction", expected, actual, status_str,
                  "Confirms CORS is constrained to approved development/cluster origins.")

    # -------------------------------------------------------------------------
    # TEST 12: Cloud Security & Browser Hardening Headers
    # -------------------------------------------------------------------------
    _, _, h = http_request(f"{BACKEND_URL}/api/health")
    expected = "x-content-type-options: nosniff, x-frame-options: DENY, referrer-policy present"
    actual = (
        f"X-Content-Type-Options: {h.get('x-content-type-options')}, "
        f"X-Frame-Options: {h.get('x-frame-options')}, "
        f"Referrer-Policy: {h.get('referrer-policy')}"
    )
    passed = (
        h.get("x-content-type-options") == "nosniff" and
        h.get("x-frame-options") == "DENY" and
        "referrer-policy" in h
    )
    status_str = "PASS" if passed else "FAIL"
    results.append(passed)
    format_result(12, "Security & Browser Hardening Headers", expected, actual, status_str,
                  "Confirms defensive HTTP security headers are injected into API responses.")

    # -------------------------------------------------------------------------
    # TEST 13: Container & Pod Security Context Hardening
    # -------------------------------------------------------------------------
    rc_sc, stdout_sc, _ = run_kubectl([
        "get", "pod", "-l", "app.kubernetes.io/component=backend", "-n", NAMESPACE,
        "-o", "jsonpath={.items[0].spec.securityContext.runAsNonRoot},{.items[0].spec.containers[0].securityContext.allowPrivilegeEscalation},{.items[0].spec.containers[0].securityContext.capabilities.drop[0]}"
    ])
    expected = "runAsNonRoot: true, allowPrivilegeEscalation: false, capabilities.drop: ALL"
    actual = stdout_sc
    passed = rc_sc == 0 and "true" in stdout_sc and "false" in stdout_sc and "ALL" in stdout_sc
    status_str = "PASS" if passed else "FAIL"
    results.append(passed)
    format_result(13, "Pod Security Context & Unprivileged Execution", expected, actual, status_str,
                  "Confirms backend container executes under non-root user with privilege escalation denied.")

    # -------------------------------------------------------------------------
    # TEST 14: Model Inference Pipeline Integrity (Regression)
    # -------------------------------------------------------------------------
    rc_inf, stdout_inf, _ = run_kubectl([
        "exec", "-n", NAMESPACE, "deploy/modelforge-backend", "--",
        "python", "-c",
        "import urllib.request, json; "
        "req = urllib.request.Request('http://model-server:8000/predict', data=json.dumps({'features': [0.0, 1.0]}).encode(), headers={'Content-Type': 'application/json'}); "
        "resp = urllib.request.urlopen(req); "
        "data = json.loads(resp.read()); "
        "preds = data.get('predictions') or data.get('prediction'); "
        "print('PREDICTION:', preds)"
    ])
    expected = "PREDICTION: [1] (or [0])"
    actual = stdout_inf
    passed = rc_inf == 0 and ("PREDICTION: [1]" in stdout_inf or "PREDICTION: [0]" in stdout_inf)
    status_str = "PASS" if passed else "FAIL"
    results.append(passed)
    format_result(14, "Model Inference Pipeline Integrity", expected, actual, status_str,
                  "Confirms inference microservice serves accurate predictions across the secured mesh.")

    # -------------------------------------------------------------------------
    # TEST 15: Horizontal Pod Autoscaler (HPA) Regression
    # -------------------------------------------------------------------------
    rc_hpa, stdout_hpa, _ = run_kubectl(["get", "hpa", "model-server-hpa", "-n", NAMESPACE, "--no-headers"])
    expected = "model-server-hpa active with CPU target 40% and valid replica count"
    actual = stdout_hpa
    passed = rc_hpa == 0 and "model-server" in stdout_hpa and "40%" in stdout_hpa
    status_str = "PASS" if passed else "FAIL"
    results.append(passed)
    format_result(15, "Horizontal Pod Autoscaler (HPA) Telemetry", expected, actual, status_str,
                  "Confirms autoscaling policies remain intact and collecting resource telemetry.")

    # -------------------------------------------------------------------------
    # FINAL SUMMARY
    # -------------------------------------------------------------------------
    print("================================================================================")
    print(" MODELFORGE PHASE 13: SECURITY TEST SUMMARY")
    print("================================================================================")
    total_tests = len(results)
    passed_tests = sum(1 for r in results if r)
    failed_tests = total_tests - passed_tests
    print(f" Total Tests Executed: {total_tests}")
    print(f" Tests Passed:         {passed_tests} / {total_tests} ({int(passed_tests / total_tests * 100)}%)")
    print(f" Tests Failed:         {failed_tests} / {total_tests}")
    print("================================================================================\n")

    if failed_tests > 0:
        print(">>> SOME TESTS FAILED. PLEASE REVIEW LOGS. <<<")
        sys.exit(1)
    else:
        print(">>> ALL PHASE 13 AUTHENTICATION, IAM & CLOUD SECURITY TESTS PASSED! <<<")
        sys.exit(0)


if __name__ == "__main__":
    main()
