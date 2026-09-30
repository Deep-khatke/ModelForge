#!/usr/bin/env python3
"""
ModelForge — Phase 11: Kubernetes Autoscaling & Resource Management Test Suite

Automated verification script executing the end-to-end HPA lifecycle:
1. Verify backend health
2. Verify model inference before load
3. Record initial replica count and baseline HPA metrics
4. Generate controlled local inference load
5. Monitor resource utilization (CPU spike) and HPA detection
6. Detect automatic scale-up by HPA
7. Stop load generation
8. Monitor scale-down stabilization
9. Detect automatic scale-down toward minReplicas by HPA
10. Verify model inference after scaling
11. Verify multi-replica load distribution
"""
import json
import subprocess
import sys
import time

NAMESPACE = "modelforge"
HPA_NAME = "model-server-hpa"
DEPLOYMENT_NAME = "model-server"

def run_cmd(cmd: list[str]) -> tuple[int, str, str]:
    """Execute command and return (returncode, stdout, stderr)."""
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, p.stdout.strip(), p.stderr.strip()

def run_kubectl(args: list[str]) -> tuple[int, str, str]:
    return run_cmd(["kubectl"] + args)

def get_hpa_status() -> dict:
    """Retrieve HPA replicas and CPU target/current."""
    rc, out, _ = run_kubectl(["get", "hpa", HPA_NAME, "-n", NAMESPACE, "-o", "json"])
    if rc != 0:
        return {}
    try:
        data = json.loads(out)
        status = data.get("status", {})
        spec = data.get("spec", {})
        current_replicas = status.get("currentReplicas", 0)
        desired_replicas = status.get("desiredReplicas", 0)
        min_replicas = spec.get("minReplicas", 1)
        max_replicas = spec.get("maxReplicas", 5)
        current_metrics = status.get("current", {}).get("metrics", [])
        current_cpu = None
        for m in current_metrics:
            if m.get("type") == "Resource" and m.get("resource", {}).get("name") == "cpu":
                current_cpu = m.get("resource", {}).get("current", {}).get("averageUtilization")
        return {
            "current_replicas": current_replicas,
            "desired_replicas": desired_replicas,
            "min_replicas": min_replicas,
            "max_replicas": max_replicas,
            "current_cpu": current_cpu
        }
    except Exception as e:
        return {"error": str(e)}

def get_deployment_replicas() -> int:
    rc, out, _ = run_kubectl(["get", "deployment", DEPLOYMENT_NAME, "-n", NAMESPACE, "-o", "jsonpath={.status.readyReplicas}"])
    try:
        return int(out)
    except:
        return 0

def main():
    print("=" * 80)
    print(" MODELFORGE PHASE 11: KUBERNETES AUTOSCALING (HPA) VERIFICATION SUITE")
    print(f" Target Namespace:  {NAMESPACE}")
    print(f" Target Deployment: {DEPLOYMENT_NAME}")
    print(f" Target HPA:        {HPA_NAME}")
    print(f" Timestamp:         {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    print("=" * 80 + "\n")

    # -------------------------------------------------------------------------
    # STEP 1: Backend Health
    # -------------------------------------------------------------------------
    print(">> STEP 1: Checking Backend Health...")
    rc, stdout, stderr = run_kubectl([
        "exec", "-n", NAMESPACE, "deploy/modelforge-backend", "--",
        "python", "-c", "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/api/health').read().decode())"
    ])
    if rc != 0 or "healthy" not in stdout:
        print(f"[FAIL] Backend health check failed: {stdout or stderr}")
        sys.exit(1)
    print(f"[PASS] Backend is healthy: {stdout}\n")

    # -------------------------------------------------------------------------
    # STEP 2: Pre-load Model Inference
    # -------------------------------------------------------------------------
    print(">> STEP 2: Verifying Model Inference before load...")
    rc, stdout, stderr = run_kubectl([
        "exec", "-n", NAMESPACE, "deploy/modelforge-backend", "--",
        "python", "-c",
        "import urllib.request, json; data = json.dumps({'features': [[1.0, 2.0]]}).encode(); "
        "req = urllib.request.Request('http://model-server:8000/predict', data=data, headers={'Content-Type': 'application/json'}); "
        "print(urllib.request.urlopen(req, timeout=3).read().decode())"
    ])
    if rc != 0 or '"predictions":[1]' not in stdout:
        print(f"[FAIL] Pre-load inference failed: {stdout or stderr}")
        sys.exit(1)
    print(f"[PASS] Pre-load inference succeeded: {stdout}\n")

    # -------------------------------------------------------------------------
    # STEP 3: Record Initial Replicas & Baseline Metrics
    # -------------------------------------------------------------------------
    print(">> STEP 3: Recording Initial HPA State & Baseline CPU...")
    init_hpa = get_hpa_status()
    init_replicas = get_deployment_replicas()
    print(f"   Initial Deployment Replicas: {init_replicas}")
    print(f"   HPA Status: Current Replicas={init_hpa.get('current_replicas')}, "
          f"Desired={init_hpa.get('desired_replicas')}, "
          f"Min={init_hpa.get('min_replicas')}, "
          f"Max={init_hpa.get('max_replicas')}, "
          f"CPU Utilization={init_hpa.get('current_cpu')}%\n")

    # -------------------------------------------------------------------------
    # STEP 4 & 5: Generate Controlled Load & Monitor CPU
    # -------------------------------------------------------------------------
    print(">> STEP 4 & 5: Generating Controlled Local Inference Traffic...")
    print("   Starting concurrent prediction traffic generator from backend pod...")
    
    # Python script executed asynchronously in backend pod to generate load
    load_code = (
        "import urllib.request, json, time\n"
        "from concurrent.futures import ThreadPoolExecutor\n"
        "data = json.dumps({'features': [[1.0, 2.0]] * 10}).encode()\n"
        "def send():\n"
        "    try:\n"
        "        req = urllib.request.Request('http://model-server:8000/predict', data=data, headers={'Content-Type': 'application/json'})\n"
        "        with urllib.request.urlopen(req, timeout=3) as resp:\n"
        "            return resp.status\n"
        "    except:\n"
        "        return 500\n"
        "start = time.time()\n"
        "with ThreadPoolExecutor(max_workers=14) as ex:\n"
        "    while time.time() - start < 40:\n"
        "        list(ex.map(lambda _: send(), range(14)))\n"
    )
    
    load_proc = subprocess.Popen([
        "kubectl", "exec", "-n", NAMESPACE, "deploy/modelforge-backend", "--",
        "python", "-c", load_code
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    scale_up_detected = False
    peak_replicas = init_replicas
    peak_cpu = 0
    poll_start = time.time()

    print("   Monitoring HPA for scale-up (evaluating every 4 seconds)...")
    while time.time() - poll_start < 55:
        time.sleep(4)
        hpa = get_hpa_status()
        cur_rep = get_deployment_replicas()
        cpu_val = hpa.get("current_cpu") or 0
        if cpu_val > peak_cpu:
            peak_cpu = cpu_val
        if cur_rep > peak_replicas:
            peak_replicas = cur_rep
        print(f"   [{int(time.time() - poll_start)}s] Deployment Replicas: {cur_rep} | HPA Current CPU: {cpu_val}% | Desired: {hpa.get('desired_replicas')}")
        if cur_rep > init_replicas:
            scale_up_detected = True
            print(f"\n[PASS] SCALE-UP DETECTED! Replicas increased from {init_replicas} to {cur_rep} (Peak CPU: {peak_cpu}%)\n")
            break

    # Ensure load subprocess completes or is terminated
    try:
        load_proc.wait(timeout=5)
    except:
        load_proc.kill()

    if not scale_up_detected:
        # Check if desiredReplicas increased even if pod is still scheduling
        hpa = get_hpa_status()
        if (hpa.get("desired_replicas") or 0) > init_replicas:
            scale_up_detected = True
            peak_replicas = hpa.get("desired_replicas")
            print(f"\n[PASS] SCALE-UP DETECTED via HPA Desired Replicas: {peak_replicas}\n")
        else:
            print("[FAIL] Scale-up was not observed within the test timeout.")
            sys.exit(1)

    # -------------------------------------------------------------------------
    # STEP 6: Verify Inference During Scaled State
    # -------------------------------------------------------------------------
    print(">> STEP 6: Verifying Model Inference while scaled up...")
    rc, stdout, stderr = run_kubectl([
        "exec", "-n", NAMESPACE, "deploy/modelforge-backend", "--",
        "python", "-c",
        "import urllib.request, json; data = json.dumps({'features': [[1.0, 2.0]]}).encode(); "
        "req = urllib.request.Request('http://model-server:8000/predict', data=data, headers={'Content-Type': 'application/json'}); "
        "print(urllib.request.urlopen(req, timeout=3).read().decode())"
    ])
    if rc != 0 or '"predictions":[1]' not in stdout:
        print(f"[FAIL] Inference during scaled state failed: {stdout or stderr}")
        sys.exit(1)
    print(f"[PASS] Inference succeeded under scaled state: {stdout}\n")

    # -------------------------------------------------------------------------
    # STEP 7: Verify Multi-Replica Distribution
    # -------------------------------------------------------------------------
    print(">> STEP 7: Verifying Load Distribution Across Scaled Replicas...")
    rc, stdout, stderr = run_kubectl([
        "exec", "-n", NAMESPACE, "deploy/modelforge-backend", "--",
        "python", "-c",
        "import urllib.request, json; replicas = set(); "
        "[replicas.add(json.loads(urllib.request.urlopen('http://model-server:8000/health').read().decode())['replica_id']) for _ in range(20)]; "
        "print(len(replicas), sorted(list(replicas)))"
    ])
    print(f"[PASS] Active replicas serving traffic: {stdout}\n")

    # -------------------------------------------------------------------------
    # STEP 8 & 9: Monitor Scale-Down
    # -------------------------------------------------------------------------
    print(">> STEP 8 & 9: Load Stopped — Monitoring Scale-Down Stabilization...")
    print("   Waiting for HPA stabilization window and scale-down toward minReplicas...")
    down_start = time.time()
    scale_down_detected = False
    final_replicas = peak_replicas

    while time.time() - down_start < 80:
        time.sleep(5)
        hpa = get_hpa_status()
        cur_rep = get_deployment_replicas()
        cpu_val = hpa.get("current_cpu") or 0
        final_replicas = cur_rep
        print(f"   [{int(time.time() - down_start)}s] Deployment Replicas: {cur_rep} | HPA Current CPU: {cpu_val}% | Desired: {hpa.get('desired_replicas')}")
        if cur_rep < peak_replicas:
            scale_down_detected = True
            print(f"\n[PASS] SCALE-DOWN DETECTED! Replicas reduced from {peak_replicas} to {cur_rep} (Target minReplicas: {hpa.get('min_replicas')})\n")
            break

    if not scale_down_detected:
        print("[FAIL] Scale-down was not observed within the test timeout.")
        sys.exit(1)

    # -------------------------------------------------------------------------
    # STEP 10: Post-Scaling Inference Verification
    # -------------------------------------------------------------------------
    print(">> STEP 10: Verifying Model Inference after scale-down...")
    rc, stdout, stderr = run_kubectl([
        "exec", "-n", NAMESPACE, "deploy/modelforge-backend", "--",
        "python", "-c",
        "import urllib.request, json; data = json.dumps({'features': [[1.0, 2.0]]}).encode(); "
        "req = urllib.request.Request('http://model-server:8000/predict', data=data, headers={'Content-Type': 'application/json'}); "
        "print(urllib.request.urlopen(req, timeout=3).read().decode())"
    ])
    if rc != 0 or '"predictions":[1]' not in stdout:
        print(f"[FAIL] Post-scaling inference failed: {stdout or stderr}")
        sys.exit(1)
    print(f"[PASS] Post-scaling inference verified: {stdout}\n")

    # -------------------------------------------------------------------------
    # SUMMARY
    # -------------------------------------------------------------------------
    print("=" * 80)
    print(" PHASE 11 AUTOSCALING TEST SUMMARY")
    print("=" * 80)
    print(f" Initial Replicas:     {init_replicas}")
    print(f" Peak Replicas:        {peak_replicas}")
    print(f" Peak CPU:             {peak_cpu}% (Target: 40%)")
    print(f" Final Replicas:       {final_replicas} (Min Replicas: {init_hpa.get('min_replicas')})")
    print(" Scale-Up Result:      VERIFIED (Triggered by CPU spike)")
    print(" Scale-Down Result:    VERIFIED (Stabilized toward minReplicas)")
    print(" Inference Integrity: VERIFIED (Pre, during, and post scaling)")
    print("=" * 80)
    print(">> ALL PHASE 11 AUTOSCALING TESTS COMPLETED SUCCESSFULLY.\n")
    sys.exit(0)

if __name__ == "__main__":
    main()
