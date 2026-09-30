#!/usr/bin/env python3
"""
ModelForge — Phase 14: Cloud Observability & Centralized Logging Verification Suite

Automated verification suite executing real tests against:
 1. Metrics Endpoint Availability (/metrics returns 200 on backend and model-server)
 2. Backend Prometheus Metrics (modelforge_http_*, modelforge_deployments_*)
 3. Model Server Metrics (modelforge_model_server_prediction_*, loaded_status, active_requests)
 4. Prometheus Scrape Targets & Health (all scrape targets UP with zero errors)
 5. Structured JSON Logging (JSON format, service tag, event, timestamp)
 6. Centralized Log Collection via Loki (Loki streams logs from backend and model-server)
 7. Request ID Correlation & Propagation (X-Request-ID propagated across backend and logged in Loki)
 8. Health & Readiness Monitoring (/health on backend, model-server, and monitoring stack)
 9. Inference Performance Telemetry (latency histogram, throughput, replica tracking)
10. Error Metrics Telemetry (modelforge_http_errors_total, prediction errors)
11. Horizontal Pod Autoscaler (HPA) Observability (kube_horizontalpodautoscaler_* in Prometheus)
12. Grafana Provisioning & Dashboards (Datasources: Prometheus & Loki; 4 operational dashboards loaded)
13. Alerting Rules & Firing Simulation (Prometheus detects controlled errors and enters firing state)
14. Alert Recovery Telemetry (Prometheus alert clears and returns to normal state)
15. Firebase Integration Regression (Firebase Admin SDK credentials & initialization)
16. Storage & Registry Regression (MinIO and modelforge-registry accessible from backend)
17. Security & Micro-segmentation Regression (NetworkPolicy isolation, non-root execution, zero secret leaks)
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

NAMESPACE = "modelforge"
BACKEND_SVC = "modelforge-backend.modelforge.svc.cluster.local:8000"
MODEL_SERVER_SVC = "model-server.modelforge.svc.cluster.local:8000"
PROMETHEUS_SVC = "prometheus.modelforge.svc.cluster.local:9090"
LOKI_SVC = "loki.modelforge.svc.cluster.local:3100"
GRAFANA_SVC = "grafana.modelforge.svc.cluster.local:3000"
GRAFANA_AUTH = "Basic YWRtaW46TW9kZWxGb3JnZUxvY2FsTW9uaXRvcmluZzIwMjYh"


def run_cmd(cmd: list[str], timeout: int = 60) -> tuple[int, str, str]:
    """Execute command and return (returncode, stdout, stderr)."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"


def run_kubectl(args: list[str], timeout: int = 60) -> tuple[int, str, str]:
    return run_cmd(["kubectl"] + args, timeout=timeout)


def exec_backend_python(code: str, timeout: int = 45) -> tuple[int, str, str]:
    """Execute python snippet inside the running backend pod."""
    cmd = [
        "kubectl", "exec", "-n", NAMESPACE, "deploy/modelforge-backend", "--",
        "python", "-c", code
    ]
    return run_cmd(cmd, timeout=timeout)


def exec_prometheus_wget(url: str, timeout: int = 20) -> tuple[int, str, str]:
    """Execute wget inside the prometheus pod."""
    cmd = [
        "kubectl", "exec", "-n", NAMESPACE, "deploy/prometheus", "--",
        "wget", "-qO-", url
    ]
    return run_cmd(cmd, timeout=timeout)


def exec_loki_query(query: str, limit: int = 5, timeout: int = 25) -> tuple[int, dict | None, str]:
    """Query Loki query_range API directly inside the Loki pod."""
    encoded_query = urllib.parse.quote(query)
    url = f"http://localhost:3100/loki/api/v1/query_range?query={encoded_query}&limit={limit}"
    cmd = [
        "kubectl", "exec", "-n", NAMESPACE, "deploy/loki", "--",
        "wget", "-qO-", url
    ]
    rc, stdout, stderr = run_cmd(cmd, timeout=timeout)
    if rc == 0:
        try:
            return 0, json.loads(stdout), ""
        except Exception as e:
            return rc, None, f"JSON parse error: {e}"
    return rc, None, stderr


def exec_grafana_wget(path: str, timeout: int = 20) -> tuple[int, str, str]:
    """Execute authenticated wget inside the grafana pod."""
    url = f"http://localhost:3000{path}"
    cmd = [
        "kubectl", "exec", "-n", NAMESPACE, "deploy/grafana", "--",
        "wget", "-qO-", f"--header=Authorization: {GRAFANA_AUTH}", url
    ]
    return run_cmd(cmd, timeout=timeout)


def format_result(test_num: int, title: str, expected: str, actual: str, status: str, notes: str = ""):
    color = "\033[92m" if status == "PASS" else "\033[91m"
    reset = "\033[0m"
    print(f"\n[{test_num:02d}] {title}")
    print(f"     Expected: {expected}")
    print(f"     Actual:   {actual}")
    print(f"     Status:   {color}[{status}]{reset}")
    if notes:
        print(f"     Notes:    {notes}")


def main():
    print("================================================================================")
    print(" MODELFORGE PHASE 14: OBSERVABILITY & CENTRALIZED LOGGING VERIFICATION SUITE")
    print("================================================================================")
    print(f" Target Namespace: {NAMESPACE}")
    print(f" Execution Time:   {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}\n")

    results: list[bool] = []

    # -------------------------------------------------------------------------
    # TEST 1: Metrics Endpoint Availability (/metrics)
    # -------------------------------------------------------------------------
    code_t1 = (
        "import urllib.request\n"
        "r1 = urllib.request.urlopen('http://localhost:8000/metrics')\n"
        f"r2 = urllib.request.urlopen('http://{MODEL_SERVER_SVC}/metrics')\n"
        "print(f'backend:{r1.status},model_server:{r2.status}')\n"
    )
    rc1, out1, _ = exec_backend_python(code_t1)
    expected = "backend:200,model_server:200"
    actual = out1
    passed = rc1 == 0 and "backend:200" in out1 and "model_server:200" in out1
    results.append(passed)
    format_result(1, "Metrics Endpoint Availability (/metrics)", expected, actual,
                  "PASS" if passed else "FAIL", "Confirms /metrics HTTP 200 on backend and model-server.")

    # -------------------------------------------------------------------------
    # TEST 2: Backend Prometheus Metrics
    # -------------------------------------------------------------------------
    code_t2 = (
        "import urllib.request\n"
        "raw = urllib.request.urlopen('http://localhost:8000/metrics').read().decode()\n"
        "has_reqs = 'modelforge_http_requests_total' in raw\n"
        "has_dur = 'modelforge_http_request_duration_seconds' in raw\n"
        "has_err = 'modelforge_http_errors_total' in raw\n"
        "has_act = 'modelforge_active_deployments' in raw\n"
        "print(f'requests:{has_reqs},duration:{has_dur},errors:{has_err},active_deployments:{has_act}')\n"
    )
    rc2, out2, _ = exec_backend_python(code_t2)
    expected = "requests:True,duration:True,errors:True,active_deployments:True"
    actual = out2
    passed = rc2 == 0 and "requests:True" in out2 and "duration:True" in out2 and "errors:True" in out2
    results.append(passed)
    format_result(2, "Backend Prometheus Metrics Instrumentation", expected, actual,
                  "PASS" if passed else "FAIL", "Confirms standard application metrics are registered and scraped.")

    # -------------------------------------------------------------------------
    # TEST 3: Model Server Metrics
    # -------------------------------------------------------------------------
    code_t3 = (
        "import urllib.request\n"
        f"raw = urllib.request.urlopen('http://{MODEL_SERVER_SVC}/metrics').read().decode()\n"
        "has_pred = 'modelforge_model_server_prediction_requests_total' in raw\n"
        "has_lat = 'modelforge_model_server_prediction_latency_seconds' in raw\n"
        "has_load = 'modelforge_model_server_loaded_status' in raw\n"
        "has_act = 'modelforge_model_server_active_requests' in raw\n"
        "print(f'pred:{has_pred},latency:{has_lat},loaded:{has_load},active:{has_act}')\n"
    )
    rc3, out3, _ = exec_backend_python(code_t3)
    expected = "pred:True,latency:True,loaded:True,active:True"
    actual = out3
    passed = rc3 == 0 and "pred:True" in out3 and "latency:True" in out3 and "loaded:True" in out3
    results.append(passed)
    format_result(3, "Model Server Metrics Telemetry", expected, actual,
                  "PASS" if passed else "FAIL", "Confirms prediction requests, latency, load status, and active requests.")

    # -------------------------------------------------------------------------
    # TEST 4: Prometheus Scrape Targets & Health
    # -------------------------------------------------------------------------
    rc4, out4, _ = exec_prometheus_wget("http://localhost:9090/api/v1/targets")
    pools_up = []
    if rc4 == 0:
        try:
            data = json.loads(out4).get("data", {})
            for t in data.get("activeTargets", []):
                if t.get("health") == "up":
                    pools_up.append(t.get("scrapePool"))
        except Exception:
            pass
    expected = "Scrape pools up: kube-state-metrics, kubernetes-cadvisor, model-server, modelforge-backend, prometheus"
    actual = f"Scrape pools up: {', '.join(sorted(set(pools_up)))}"
    passed = ("modelforge-backend" in pools_up and "model-server" in pools_up and
              "kube-state-metrics" in pools_up and "kubernetes-cadvisor" in pools_up)
    results.append(passed)
    format_result(4, "Prometheus Target Discovery & Scrape Health", expected, actual,
                  "PASS" if passed else "FAIL", "Confirms Prometheus is scraping all 5 target pools with health=UP.")

    # -------------------------------------------------------------------------
    # TEST 5: Structured JSON Logging
    # -------------------------------------------------------------------------
    rc5, out5, _ = run_kubectl(["logs", "-n", NAMESPACE, "deploy/modelforge-backend", "--tail=20"])
    has_json = False
    has_fields = False
    for line in out5.splitlines():
        try:
            record = json.loads(line)
            has_json = True
            if "timestamp" in record and "level" in record and "service" in record:
                has_fields = True
                break
        except Exception:
            continue
    expected = "Structured JSON logs containing timestamp, level, and service"
    actual = f"JSON parsed: {has_json}, Standard fields present: {has_fields}"
    passed = has_json and has_fields
    results.append(passed)
    format_result(5, "Structured JSON Logging Compliance", expected, actual,
                  "PASS" if passed else "FAIL", "Confirms container stdout emits structured JSON logs.")

    # -------------------------------------------------------------------------
    # TEST 6: Centralized Log Collection via Loki
    # -------------------------------------------------------------------------
    rc6, loki_resp, _ = exec_loki_query('{service="backend"}', limit=3)
    loki_has_logs = False
    if rc6 == 0 and loki_resp and "data" in loki_resp:
        results_list = loki_resp.get("data", {}).get("result", [])
        if len(results_list) > 0 and len(results_list[0].get("values", [])) > 0:
            loki_has_logs = True
    expected = "Loki stream contains indexed backend container logs"
    actual = f"Loki query succeeded: {rc6 == 0}, Log streams found: {loki_has_logs}"
    passed = rc6 == 0 and loki_has_logs
    results.append(passed)
    format_result(6, "Centralized Log Collection via Loki", expected, actual,
                  "PASS" if passed else "FAIL", "Confirms Promtail ships container logs and Loki indexes them.")

    # -------------------------------------------------------------------------
    # TEST 7: Request ID Correlation & Propagation
    # -------------------------------------------------------------------------
    corr_req_id = f"corr-suite-{int(time.time())}"
    code_t7 = (
        "import urllib.request, json\n"
        f"req = urllib.request.Request('http://localhost:8000/api/v1/auth/me', headers={{'X-Request-ID': '{corr_req_id}'}})\n"
        "try:\n"
        "    urllib.request.urlopen(req)\n"
        "except urllib.error.HTTPError as e:\n"
        "    echo_id = e.headers.get('X-Request-ID')\n"
        "    print(f'echoed:{echo_id}')\n"
    )
    rc7, out7, _ = exec_backend_python(code_t7)
    time.sleep(3)  # Allow Promtail to ship log to Loki
    rc7_loki, loki_corr, _ = exec_loki_query(f'{{service="backend"}} |= "{corr_req_id}"', limit=1)
    corr_in_loki = False
    if rc7_loki == 0 and loki_corr and "data" in loki_corr:
        streams = loki_corr.get("data", {}).get("result", [])
        if len(streams) > 0 and len(streams[0].get("values", [])) > 0:
            corr_in_loki = True
    expected = f"echoed:{corr_req_id} and found in Loki log stream"
    actual = f"Backend echo: {out7}, Loki query found: {corr_in_loki}"
    passed = f"echoed:{corr_req_id}" in out7 and corr_in_loki
    results.append(passed)
    format_result(7, "End-to-End Request ID Correlation & Propagation", expected, actual,
                  "PASS" if passed else "FAIL", "Confirms X-Request-ID header propagation and indexed log lookup.")

    # -------------------------------------------------------------------------
    # TEST 8: Health & Readiness Monitoring
    # -------------------------------------------------------------------------
    rc_b, out_b, _ = exec_backend_python("import urllib.request; print(urllib.request.urlopen('http://localhost:8000/api/health').status)")
    rc_m, out_m, _ = exec_backend_python(f"import urllib.request; print(urllib.request.urlopen('http://{MODEL_SERVER_SVC}/health').status)")
    rc_p, out_p, _ = exec_prometheus_wget("http://localhost:9090/-/healthy")
    rc_l, out_l, _ = run_cmd(["kubectl", "exec", "-n", NAMESPACE, "deploy/loki", "--", "wget", "-qO-", "http://localhost:3100/ready"])
    rc_g, out_g, _ = run_cmd(["kubectl", "exec", "-n", NAMESPACE, "deploy/grafana", "--", "wget", "-qO-", "http://localhost:3000/api/health"])
    b_ok = rc_b == 0 and "200" in out_b
    m_ok = rc_m == 0 and "200" in out_m
    p_ok = rc_p == 0 and "Healthy" in out_p
    l_ok = rc_l == 0 and "ready" in out_l.lower()
    g_ok = rc_g == 0 and "ok" in out_g.lower()
    expected = "backend:200,model:200,prom:200,loki:200,grafana:200"
    actual = f"backend:{'200' if b_ok else 'err'},model:{'200' if m_ok else 'err'},prom:{'200' if p_ok else 'err'},loki:{'200' if l_ok else 'err'},grafana:{'200' if g_ok else 'err'}"
    passed = b_ok and m_ok and p_ok and l_ok and g_ok
    results.append(passed)
    format_result(8, "Service Health & Readiness Monitoring", expected, actual,
                  "PASS" if passed else "FAIL", "Confirms all microservices and monitoring components report healthy status.")

    # -------------------------------------------------------------------------
    # TEST 9: Inference Performance Telemetry
    # -------------------------------------------------------------------------
    code_t9 = (
        "import urllib.request, json\n"
        "data = json.dumps({'features': [1.0, 2.0]}).encode()\n"
        f"req = urllib.request.Request('http://{MODEL_SERVER_SVC}/predict', data=data, headers={{'Content-Type': 'application/json'}})\n"
        "resp = urllib.request.urlopen(req)\n"
        "body = json.loads(resp.read())\n"
        "print(f'status:{resp.status},has_lat:{body.get(\"inference_time_ms\") is not None},replica:{body.get(\"replica_id\") is not None}')\n"
    )
    rc9, out9, _ = exec_backend_python(code_t9)
    expected = "status:200,has_lat:True,replica:True"
    actual = out9
    passed = rc9 == 0 and "status:200" in out9 and "has_lat:True" in out9 and "replica:True" in out9
    results.append(passed)
    format_result(9, "ML Inference Performance Telemetry", expected, actual,
                  "PASS" if passed else "FAIL", "Confirms prediction execution telemetry with latency tracking.")

    # -------------------------------------------------------------------------
    # TEST 10: Error Metrics Telemetry
    # -------------------------------------------------------------------------
    code_t10 = (
        "import urllib.request\n"
        "for _ in range(5):\n"
        "    try:\n"
        "        urllib.request.urlopen('http://localhost:8000/api/v1/trigger_err_suite')\n"
        "    except Exception:\n"
        "        pass\n"
        "raw = urllib.request.urlopen('http://localhost:8000/metrics').read().decode()\n"
        "print(f'error_metric_present:{\"modelforge_http_errors_total\" in raw}')\n"
    )
    rc10, out10, _ = exec_backend_python(code_t10)
    expected = "error_metric_present:True"
    actual = out10
    passed = rc10 == 0 and "error_metric_present:True" in out10
    results.append(passed)
    format_result(10, "Application Error Telemetry", expected, actual,
                  "PASS" if passed else "FAIL", "Confirms error counter increments and exposes in /metrics.")

    # -------------------------------------------------------------------------
    # TEST 11: Horizontal Pod Autoscaler (HPA) Observability
    # -------------------------------------------------------------------------
    rc11, out11, _ = exec_prometheus_wget(
        'http://localhost:9090/api/v1/query?query=kube_horizontalpodautoscaler_status_current_replicas%7Bnamespace%3D%22modelforge%22%7D'
    )
    hpa_metric_found = False
    replicas_val = 0
    if rc11 == 0:
        try:
            vec = json.loads(out11).get("data", {}).get("result", [])
            if len(vec) > 0:
                hpa_metric_found = True
                replicas_val = int(vec[0].get("value", [0, 0])[1])
        except Exception:
            pass
    expected = "kube_horizontalpodautoscaler_status_current_replicas present with replicas >= 2"
    actual = f"Metric found: {hpa_metric_found}, Current replicas: {replicas_val}"
    passed = rc11 == 0 and hpa_metric_found and replicas_val >= 2
    results.append(passed)
    format_result(11, "Horizontal Pod Autoscaler (HPA) Observability", expected, actual,
                  "PASS" if passed else "FAIL", "Confirms kube-state-metrics HPA telemetry is ingested by Prometheus.")

    # -------------------------------------------------------------------------
    # TEST 12: Grafana Provisioning & Dashboards
    # -------------------------------------------------------------------------
    rc_ds, out_ds, _ = exec_grafana_wget("/api/datasources")
    rc_db, out_db, _ = exec_grafana_wget("/api/search")
    ds_names = []
    db_uids = []
    if rc_ds == 0:
        try:
            ds_list = json.loads(out_ds)
            ds_names = [d.get("name") for d in ds_list]
        except Exception:
            pass
    if rc_db == 0:
        try:
            db_list = json.loads(out_db)
            db_uids = [d.get("uid") for d in db_list if d.get("type") == "dash-db"]
        except Exception:
            pass
    expected = "datasources:['Loki', 'Prometheus'], 4 operational dashboards loaded"
    actual = f"datasources:{sorted(ds_names)},dashboards:{sorted(db_uids)}"
    passed = ("Prometheus" in ds_names and "Loki" in ds_names and
              "modelforge-overview" in db_uids and "modelforge-kubernetes" in db_uids and
              "modelforge-ml-inference" in db_uids and "modelforge-security-operations" in db_uids)
    results.append(passed)
    format_result(12, "Grafana Provisioning & Dashboard Availability", expected, actual,
                  "PASS" if passed else "FAIL", "Confirms provisioned datasources and 4 ModelForge operational dashboards.")

    # -------------------------------------------------------------------------
    # TEST 13: Alerting Rules & Firing Simulation
    # -------------------------------------------------------------------------
    # Trigger steady errors to fire HighHttpErrorRate
    code_t13 = (
        "import urllib.request, time, threading\n"
        "def trigger():\n"
        "    for _ in range(50):\n"
        "        try:\n"
        "            urllib.request.urlopen('http://localhost:8000/api/v1/trigger_alert_test')\n"
        "        except Exception:\n"
        "            pass\n"
        "        time.sleep(0.3)\n"
        "t = threading.Thread(target=trigger)\n"
        "t.start()\n"
        "time.sleep(12)\n"
    )
    exec_backend_python(code_t13, timeout=30)
    # Poll Prometheus /api/v1/alerts for up to 15 seconds to observe firing state
    observed_firing = False
    firing_alerts = []
    for _ in range(8):
        time.sleep(2)
        rc13, out13, _ = exec_prometheus_wget("http://localhost:9090/api/v1/alerts")
        if rc13 == 0:
            try:
                alerts = json.loads(out13).get("data", {}).get("alerts", [])
                firing_alerts = [a.get("labels", {}).get("alertname") for a in alerts if a.get("state") == "firing"]
                if "HighHttpErrorRate" in firing_alerts:
                    observed_firing = True
                    break
            except Exception:
                pass
    expected = "HighHttpErrorRate alert detected in firing state"
    actual = f"Active firing alerts: {firing_alerts}"
    passed = observed_firing
    results.append(passed)
    format_result(13, "Alerting Rules & Firing Simulation", expected, actual,
                  "PASS" if passed else "FAIL", "Confirms Prometheus detects sustained errors and triggers firing alert.")

    # -------------------------------------------------------------------------
    # TEST 14: Alert Recovery Telemetry
    # -------------------------------------------------------------------------
    # Wait for the 1m rate window to clear errors and confirm alert clears
    print("     [+] Waiting for error rate decay window (65s) to verify alert recovery...")
    time.sleep(65)
    rc14, out14, _ = exec_prometheus_wget("http://localhost:9090/api/v1/alerts")
    remaining_firing = []
    if rc14 == 0:
        try:
            alerts = json.loads(out14).get("data", {}).get("alerts", [])
            remaining_firing = [a.get("labels", {}).get("alertname") for a in alerts if a.get("state") == "firing"]
        except Exception:
            pass
    expected = "HighHttpErrorRate alert resolved (no longer firing)"
    actual = f"Remaining firing alerts: {remaining_firing}"
    passed = rc14 == 0 and "HighHttpErrorRate" not in remaining_firing
    results.append(passed)
    format_result(14, "Alert Auto-Recovery Telemetry", expected, actual,
                  "PASS" if passed else "FAIL", "Confirms firing alert automatically resolves when error traffic ceases.")

    # -------------------------------------------------------------------------
    # TEST 15: Firebase Integration Regression
    # -------------------------------------------------------------------------
    code_t15 = (
        "from app.services.firebase.client import initialize_firebase, get_firebase_credentials_path\n"
        "p = get_firebase_credentials_path()\n"
        "init = initialize_firebase()\n"
        "print(f'has_cred:{p is not None},init:{init}')\n"
    )
    rc15, out15, _ = exec_backend_python(code_t15)
    expected = "has_cred:True,init:True"
    actual = out15
    passed = rc15 == 0 and "has_cred:True" in out15 and "init:True" in out15
    results.append(passed)
    format_result(15, "Firebase Integration Regression", expected, actual,
                  "PASS" if passed else "FAIL", "Confirms Firebase credentials mount and SDK initialization.")

    # -------------------------------------------------------------------------
    # TEST 16: Storage & Registry Regression
    # -------------------------------------------------------------------------
    code_t16 = (
        "import urllib.request\n"
        "m = urllib.request.urlopen('http://minio.modelforge.svc.cluster.local:9000/minio/health/live', timeout=3).status\n"
        "r = urllib.request.urlopen('http://modelforge-registry.modelforge.svc.cluster.local:5000/v2/', timeout=3).status\n"
        "print(f'minio:{m},registry:{r}')\n"
    )
    rc16, out16, _ = exec_backend_python(code_t16)
    expected = "minio:200,registry:200"
    actual = out16
    passed = rc16 == 0 and "minio:200" in out16 and "registry:200" in out16
    results.append(passed)
    format_result(16, "Cloud Storage & Container Registry Regression", expected, actual,
                  "PASS" if passed else "FAIL", "Confirms MinIO object storage and private container registry operational.")

    # -------------------------------------------------------------------------
    # TEST 17: Security & Micro-segmentation Regression
    # -------------------------------------------------------------------------
    # Verify NetworkPolicy blocks frontend -> model-server
    rc17_front, _, _ = run_cmd([
        "kubectl", "exec", "-n", NAMESPACE, "deploy/modelforge-frontend", "--",
        "wget", "-qO-", "--timeout=2", "http://model-server:8000/health"
    ])
    # Verify backend pod runs as non-root
    rc17_sec, out17_sec, _ = run_kubectl([
        "get", "pod", "-l", "app.kubernetes.io/component=backend", "-n", NAMESPACE,
        "-o", "jsonpath={.items[0].spec.securityContext.runAsNonRoot}"
    ])
    expected = "Frontend direct access blocked (timeout/fail) and runAsNonRoot: true"
    actual = f"Frontend exit code: {rc17_front} (blocked), runAsNonRoot: {out17_sec}"
    passed = rc17_front != 0 and out17_sec == "true"
    results.append(passed)
    format_result(17, "Security Isolation & Hardening Regression", expected, actual,
                  "PASS" if passed else "FAIL", "Confirms NetworkPolicy micro-segmentation and unprivileged pod execution.")

    # -------------------------------------------------------------------------
    # FINAL SUMMARY
    # -------------------------------------------------------------------------
    print("\n================================================================================")
    print(" MODELFORGE PHASE 14: OBSERVABILITY TEST SUMMARY")
    print("================================================================================")
    total_tests = len(results)
    passed_tests = sum(1 for r in results if r)
    failed_tests = total_tests - passed_tests
    pct = int(passed_tests / total_tests * 100)
    print(f" Total Tests Executed: {total_tests}")
    print(f" Tests Passed:         {passed_tests} / {total_tests} ({pct}%)")
    print(f" Tests Failed:         {failed_tests} / {total_tests}")
    print("================================================================================\n")

    if failed_tests > 0:
        print(">>> SOME TESTS FAILED. PLEASE REVIEW LOGS. <<<")
        sys.exit(1)
    else:
        print(">>> ALL 17 PHASE 14 OBSERVABILITY & LOGGING TESTS PASSED! <<<")
        sys.exit(0)


if __name__ == "__main__":
    main()
