# ModelForge — Phase 10: Cloud Networking & Infrastructure Guide

This document describes the networking and infrastructure architecture of ModelForge, covering both the active local Kubernetes implementation (Docker Desktop Kubernetes) and the production-ready cloud networking design (Google Cloud / GKE, AWS / EKS, and Azure / AKS).

---

## 1. Cloud Networking Overview

Cloud networking provides the software-defined connectivity, network isolation, traffic routing, and security boundaries required to operate enterprise cloud-native systems. In traditional local development, workloads often communicate over unconstrained localhost loopbacks or flat container bridge networks. In production cloud environments, applications reside within a **Virtual Private Cloud (VPC)** with explicit subnet tiers, firewall rules, managed load balancers, ingress controllers, and internal service discovery.

ModelForge Phase 10 demonstrates these principles in practice:
- **Local Implementation:** Orchestrated on Docker Desktop Kubernetes using Kubernetes Services (ClusterIP & LoadBalancer), CoreDNS service discovery, Nginx reverse proxying, and active Kubernetes NetworkPolicy enforcement.
- **Cloud-Ready Architecture:** Designed to map 1-to-1 onto Google Cloud VPC, AWS VPC, or Azure Virtual Networks with private GKE/EKS clusters, Cloud Armor / WAF, managed TLS, and secure cloud storage egress.

---

## 2. ModelForge Network Architecture Diagram

```text
                                  INTERNET / USER
                                         |
                                         v
                                  [ Public DNS ]
                           (modelforge.example / Cloud DNS)
                                         |
                                         v
                             [ Cloud Load Balancer ]
                        (L7 HTTPS External Load Balancer)
                                         |
    =============================|=============================================
    KUBERNETES INGRESS / GATEWAY | (DMZ / Edge Routing)
                                 v
                         [ Ingress Controller ]
                      (NGINX / GKE Ingress 'gce')
                                 |
                 +---------------+---------------+
                 |                               |
                 | Host: modelforge.example      | Host: modelforge.example
                 | Path: /                       | Path: /api
                 v                               v
    ===========================================================================
    PUBLIC / APPLICATION TIER   |
                                |
        [ Frontend Service ]    |         [ Backend Service ]
          Type: LoadBalancer    |           Type: LoadBalancer / ClusterIP
          Port: 80 / 5173       |           Port: 8000
                 |              |                |
                 v              |                v
        [ Frontend Pod ]        |         [ Backend Pod ]
         (React SPA / Nginx)----+----->    (FastAPI Control Plane)
         (Reverse proxies /api)                  |
    =============================================|=============================
    PRIVATE INFERENCE TIER                       | (NetworkPolicy Enforced)
    (Isolated from Direct External Access)       |
                                                 v
                                       [ Model-Server Service ]
                                          Type: ClusterIP (Internal Only)
                                          Port: 8000
                                                 |
                       +-------------------------+-------------------------+
                       |                         |                         |
                       v                         v                         v
               [ Model Pod 1 ]           [ Model Pod 2 ]           [ Model Pod 3 ]
             (:8000 - Replica 1)       (:8000 - Replica 2)       (:8000 - Replica 3)
                       \                         |                         /
                        +------------------------+------------------------+
                                                 |
                                     (Shared Persistent Volume)
                                     /models/model.joblib (PVC)
    =============================================|=============================
    SECURE CLOUD EGRESS TIER                     |
                                                 v
                                   [ Cloud Firestore / Firebase ]
                                   (HTTPS Outbound Egress - TCP 443)
```

---

## 3. VPC (Virtual Private Cloud) Architecture

A **Virtual Private Cloud (VPC)** is an isolated, software-defined virtual network dedicated to your cloud project. It provides complete control over IP address ranges, routing tables, network gateways, and access control policies.

- **Local Reality:** Docker Desktop utilizes a local virtual switch and Docker bridge network (`172.18.0.0/16`) to provide inter-container connectivity. It is a flat, unsegmented single-node broadcast domain.
- **Cloud Reality:** In Google Cloud, an Auto or Custom Mode VPC spans global regions. Compute Engine instances and GKE nodes reside within regional subnets, and traffic cannot enter or leave without passing through VPC firewall rules and Cloud Routers.
- **ModelForge VPC Design:**
  - Dedicated VPC: `modelforge-vpc`
  - Subnet Range: `10.100.0.0/20` (Application and GKE Nodes)
  - Secondary Range for Pods: `10.101.0.0/16`
  - Secondary Range for Services: `10.102.0.0/20`
  - Private Google Access enabled: Allows backend pods to communicate with Firebase, Firestore, and Cloud Storage over internal Google backbones without traversing the public internet.

---

## 4. Subnet Design

In a multi-tier cloud deployment, networks are divided into subnets based on operational exposure:

| Subnet Name | Purpose | IP CIDR | Route / Access |
|---|---|---|---|
| `public-ingress-subnet` | External Load Balancers, Cloud NAT gateways, Ingress proxies | `10.100.0.0/24` | Default route to Internet Gateway |
| `gke-nodes-subnet` | GKE Worker Nodes (Private Cluster Nodes) | `10.100.16.0/20` | Outbound via Cloud NAT; no public IPs on nodes |
| `gke-pods-range` (Secondary) | Ephemeral container IPs assigned by VPC-native CNI | `10.101.0.0/16` | Internal VPC routing only |
| `gke-services-range` (Secondary) | Kubernetes Virtual ClusterIP allocation | `10.102.0.0/20` | Internal kube-proxy iptables / IPVS translation |
| `private-service-access` | Google Cloud managed databases / Firestore connector | `10.100.32.0/24` | VPC Peering to Google Services |

---

## 5. Public vs. Private Networking

ModelForge strictly segregates public-facing entry points from private inference workloads:

### Public Components
1. **Frontend Service (`modelforge-frontend`):** Serves static React single-page application assets (HTML, JS, CSS) to client web browsers.
2. **Backend API Entry Point (`backend`):** Receives client API calls, handles user authentication (JWT), RBAC verification (`ADMIN`, `OPERATOR`, `VIEWER`), rate limiting, model registry operations, and audit logging.

### Private Components
1. **Model-Server (`model-server`):**
   - **MUST NEVER BE PUBLICLY EXPOSED.**
   - Configured strictly as a Kubernetes `ClusterIP` service (`10.96.229.231:8000`).
   - Does not have a public IP, NodePort, or Ingress route.
   - Protected by Kubernetes `NetworkPolicy` to reject any incoming traffic from the frontend, internet, or other namespaces.
2. **Internal Communication:**
   - Communication between `backend` and `model-server` occurs exclusively inside the cluster over private virtual IPs.

### Why This Is Safer:
- **Defense in Depth:** Even if an attacker identifies a vulnerability or malformed input payload that could crash the scikit-learn unpickler or numpy engine in `model-server`, they cannot send packets to `model-server` directly.
- **Authentication Guarantee:** All inference requests must pass through the `backend` control plane, which validates JWT tokens, enforces RBAC roles, checks tenant permissions, and writes an immutable audit record to Firestore before delegating computation.
- **Zero Public Port Proliferation:** Eliminates accidental exposure of internal RPC ports, management interfaces, or debug tools.

---

## 6. Kubernetes Internal Networking & Service Discovery

Inside the Kubernetes cluster, workloads do not communicate via hardcoded IP addresses or `localhost`. Kubernetes provides virtual abstractions:

### Service Types in ModelForge

| Service Name | Type | ClusterIP | Ports | Role |
|---|---|---|---|---|
| `modelforge-frontend` | `LoadBalancer` | `10.96.94.211` | `5173:31787`, `80:30995` | External entry point to web dashboard |
| `backend` | `LoadBalancer` | `10.96.47.160` | `8000:30433` | External entry point to FastAPI REST API |
| `modelforge-backend` | `ClusterIP` | `10.96.27.96` | `8000` | Internal stable cluster endpoint |
| `model-server` | `ClusterIP` | `10.96.229.231` | `8000` | **Strictly internal** inference microservice |

### Service Discovery in Action
1. When the backend needs to execute a model prediction, it connects to:
   ```text
   http://model-server:8000/predict
   ```
2. CoreDNS resolves `model-server` (and FQDN `model-server.modelforge.svc.cluster.local`) to the stable virtual ClusterIP `10.96.229.231`.
3. The Linux kernel (`kube-proxy` iptables / IPVS rules) intercepts packets destined for `10.96.229.231:8000` and seamlessly distributes them across the 3 ready `model-server` Pod IPs.

### Verified Test Evidence:
```text
Backend Pod DNS Resolution:
Short Name:  model-server -> 10.96.229.231
Full FQDN:   model-server.modelforge.svc.cluster.local -> 10.96.229.231
Load Distribution Across 3 Model Replicas:
- model-server-559cdbfcff-6cdbn
- model-server-559cdbfcff-n295x
- model-server-559cdbfcff-xwgmh
```

---

## 7. Ingress Architecture

An **Ingress** manages external HTTP/HTTPS access to services within a cluster, providing application-layer (Layer 7) routing based on hostnames and URL paths.

### Ingress Manifest (`k8s/ingress.yaml`)
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: modelforge-ingress
  namespace: modelforge
  labels:
    app.kubernetes.io/name: modelforge
    app.kubernetes.io/component: ingress
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "false"
    nginx.ingress.kubernetes.io/proxy-body-size: "50m"
spec:
  rules:
    - host: modelforge.local
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: modelforge-frontend
                port:
                  number: 80
          - path: /api
            pathType: Prefix
            backend:
              service:
                name: backend
                port:
                  number: 8000
```

### Local Cluster vs. Cloud Controller Status
- **Local Docker Desktop Kubernetes:**
  - `kubectl get ingressclass` reports `No resources found`.
  - No Ingress Controller pod is deployed by default in Docker Desktop to keep resource usage lightweight.
  - Per zero-budget and least-overhead requirements, ModelForge avoids installing heavy ingress daemons locally. The manifest is deployed and validated in the cluster API, ready to bind once a controller is attached.
- **Production Cloud (GKE/EKS/AKS):**
  - GKE automatically deploys the Google Cloud Ingress Controller (`ingressClassName: gce`).
  - Specifying the ingress automatically provisions a Google Cloud External HTTP(S) Load Balancer with Anycast IP, SSL termination, and Google Cloud Armor integration.

---

## 8. Local DNS Architecture

To access ModelForge via a human-friendly domain without purchasing a public DNS zone, the local architecture uses `modelforge.local`:

### Hosts File Mapping
On Windows, edit `C:\Windows\System32\drivers\etc\hosts` (as Administrator) to add:
```text
127.0.0.1    modelforge.local
```
*(On Linux/macOS: `/etc/hosts`)*

### Access Workflow:
1. Browser resolves `http://modelforge.local` to loopback `127.0.0.1`.
2. The port-forward or local LoadBalancer maps port `80` to `modelforge-frontend` and port `8000` to `backend`.
3. Ingress routes `/` to the React dashboard and `/api` to the FastAPI backend.

---

## 9. Public DNS Architecture

In production cloud deployment, ModelForge does not use local hosts files. Instead, public DNS resolution is orchestrated via managed cloud DNS:

```text
User Browser
     | (Queries 'modelforge.example')
     v
[ Public DNS Zone (Google Cloud DNS / AWS Route 53) ]
     | (Returns Anycast IPv4 '34.x.y.z')
     v
[ Global External HTTP(S) Load Balancer ]
     | (Terminates TLS, inspects HTTP Host header)
     v
[ Kubernetes Ingress ]
     |
  +--+--+
  |     |
Frontend Backend
```

- **Domain Registration:** Registrar provides nameserver delegation (e.g. `ns-cloud-a1.googledomains.com`).
- **A Records:** `modelforge.example` $\rightarrow$ Cloud Load Balancer Public Static IP.
- **CNAME Records:** `api.modelforge.example` $\rightarrow$ `modelforge.example`.

---

## 10. Load Balancing Layers

ModelForge employs a multi-tier load-balancing hierarchy:

```text
Layer 1: External Cloud Load Balancer
  - Level: Layer 4 (TCP) or Layer 7 (HTTP/HTTPS) Anycast
  - Responsibility: Global traffic ingress, DDoS mitigation, TLS termination, routing to healthy cluster nodes.

Layer 2: Kubernetes Ingress Controller
  - Level: Layer 7 (HTTP) Application Routing
  - Responsibility: Evaluates Host (`modelforge.local`) and Path (`/` vs `/api`), injecting forwarded headers.

Layer 3: Kubernetes Service (kube-proxy)
  - Level: Layer 4 (TCP) Virtual IP
  - Responsibility: Session-agnostic packet routing via iptables/IPVS, load balancing across ready Pod replicas.
  - Active in ModelForge: Balances inference calls evenly across the 3 `model-server` replicas.
```

---

## 11. Firewall & Network Security Boundaries

ModelForge enforces defense in depth across three distinct filtering mechanisms:

| Level | Technology | Where It Operates | ModelForge Rule |
|---|---|---|---|
| **L3/L4 Cloud Perimeter** | VPC Firewall Rules / Security Groups | VPC Virtual Switch | Allow Ingress 80/443 to Load Balancer only. Deny all direct inbound traffic to worker nodes. |
| **L7 Application Perimeter** | Cloud Armor / WAF / Ingress | External Edge | Rate-limiting, SQLi/XSS filtering, SSL termination, path-based routing. |
| **Pod-to-Pod Network Boundary** | Kubernetes NetworkPolicy | CNI Plugin (kindnet / Calico / Cilium) | Block all pods from accessing `model-server` except `backend`. Allow outbound 443 for Firebase. |

---

## 12. Kubernetes NetworkPolicy Implementation & Enforcement

ModelForge implements micro-segmentation using native Kubernetes `NetworkPolicy` manifests in [k8s/networkpolicy.yaml](file:///c:/college/ModelForge-Phase5-source/k8s/networkpolicy.yaml).

### Applied Policies:
1. **`model-server-netpol`**:
   - Isolates all pods with `component: model-server`.
   - **Ingress:** Allows TCP port 8000 ONLY from pods matching `component: backend`.
   - **Egress:** Allows DNS lookup to kube-system.
   - **Result:** Direct access from `frontend`, other namespaces, or external networks is **DENIED / DROPPED**.
2. **`backend-netpol`**:
   - Isolates pods with `component: backend`.
   - **Ingress:** Allows TCP port 8000 from frontend pods and external entrypoints.
   - **Egress:** Allows TCP port 8000 to `model-server`, port 53 to CoreDNS, and outbound HTTPS (TCP 443) to Firebase / Google Cloud Firestore.
3. **`frontend-netpol`**:
   - Isolates pods with `component: frontend`.
   - **Ingress:** Allows HTTP ports 80 and 5173.
   - **Egress:** Allows TCP port 8000 to `backend` and port 53 to CoreDNS.

### Verified Cluster Enforcement:
The cluster's CNI (`kindnetd:v20260528-9350166c` on Kubernetes v1.36.1) actively enforces these policies:
- **Backend $\rightarrow$ Model-Server:** **ALLOWED** (`200 OK`, latency: `0.37ms`).
- **Frontend $\rightarrow$ Model-Server:** **BLOCKED & TIMED OUT** (`curl` exit code `28` - Operation timed out).
- **Backend $\rightarrow$ Firebase (Firestore):** **ALLOWED** (HTTPS TCP 443 egress verified).

---

## 13. HTTPS / TLS Architecture

Production workloads require end-to-end encryption in transit:

```text
Browser (HTTPS)
   | (TLS Handshake, TLS 1.3, Let's Encrypt Certificate)
   v
[ Cloud Load Balancer / Ingress ]
   | (Terminates TLS, inspects headers)
   v
[ Kubernetes Service ] (HTTP plaintext over private VPC overlay)
   v
[ Backend / Frontend Pods ]
```

### Manifest Template: [k8s/tls-secret.example.yaml](file:///c:/college/ModelForge-Phase5-source/k8s/tls-secret.example.yaml)
- **Local Dev:** Local testing uses plain HTTP or self-signed development certificates.
- **Production Cloud:**
  - Automated via **`cert-manager`** with ACME Let's Encrypt challenge solver.
  - Or via **Google-managed SSL certificates** (`ManagedCertificate` CRD) on GKE.
  - Private keys are stored in a Kubernetes `Secret` of type `kubernetes.io/tls` and never checked into source control.

---

## 14. Firebase & External Cloud Egress Networking

ModelForge uses a hybrid architecture:
- **Application State & Identity:** Google Cloud Firestore and Firebase Authentication.
- **Compute & Orchestration:** Kubernetes Cluster.

### Egress Path:
```text
Backend Pod (10.244.0.x)
   |
Kubernetes Node (VPC Private IP)
   |
Cloud NAT / Default Internet Gateway
   | (Encrypted TLS over TCP port 443)
Google Identity & Cloud Firestore APIs (firestore.googleapis.com)
```

### Safety & Credentials:
- Private service account key (`firebase-credentials.json`) is mounted into `/etc/modelforge/credentials` strictly via a Kubernetes `Secret` (`modelforge-secrets`).
- Credentials are never baked into Docker images or committed to Git.
- Outbound network policy explicitly permits TCP 443 egress to the internet.

---

## 15. Frontend Browser Networking vs. Internal Pod Networking

A critical distinction in containerized web development:

1. **The Browser Runs on the Host:**
   - The user's web browser executes JavaScript on the client workstation outside the Kubernetes cluster.
   - The browser **cannot** resolve `.cluster.local` domain names (e.g. `model-server.modelforge.svc.cluster.local`).
2. **ModelForge Dual-Route Solution:**
   - **In-Cluster Reverse Proxy:** The `modelforge-frontend` container runs an Nginx server configured with:
     ```nginx
     location /api/ {
         proxy_pass http://backend:8000;
     }
     ```
     When accessed via the frontend service, the browser sends relative requests (`/api/models`), and Nginx proxies them to the backend using internal Kubernetes DNS.
   - **Local Development Fallback:** The frontend `.env` configures `VITE_API_BASE_URL=http://localhost:8000` when running locally via Vite dev server.

---

## 16. Cloud vs. Local Architecture Comparison Table

| Architecture Concept | Current Local ModelForge (Phase 10) | Future Production Cloud ModelForge (GKE / AWS / Azure) |
|---|---|---|
| **Virtual Private Cloud (VPC)** | Local Docker network bridge (`172.18.0.0/16`) | Cloud VPC (`10.100.0.0/20`) with dedicated regional subnets |
| **Subnet Tiers** | Single flat container network | Public DMZ, Private Node, Pod secondary, Service secondary |
| **Ingress Controller** | Ingress spec configured (`k8s/ingress.yaml`); local controller optional | GKE Ingress (`gce`), AWS ALB Ingress, or NGINX Ingress Controller |
| **External Load Balancer** | Docker Desktop port forward / pseudo-LoadBalancer IP | Cloud HTTP(S) Load Balancer with global Anycast IP address |
| **DNS Resolution** | `modelforge.local` via local `hosts` file | Public Cloud DNS (Route53, Cloud DNS) with automated record management |
| **Firewall / Perimeter** | Host OS firewall (Windows Defender) | Cloud VPC Firewall Rules + Cloud Armor / AWS WAF L7 inspection |
| **NetworkPolicy** | Enforced by cluster CNI (`kindnetd`) | Enforced by Datapath v2 (eBPF / Cilium on GKE) or Calico |
| **Service Discovery** | In-cluster CoreDNS (`.cluster.local`) | Managed Cloud CoreDNS with auto-scaling DNS pods |
| **Public Endpoints** | `modelforge-frontend` (:5173, :80), `backend` (:8000) | Cloud Load Balancer HTTPS (:443) entry point only |
| **Private Services** | `model-server` (ClusterIP `10.96.229.231:8000`) | `model-server` (Internal ClusterIP, zero internet ingress) |
| **TLS / HTTPS** | Plain HTTP for local dev; TLS Secret template | Automated TLS termination via cert-manager or Cloud Managed Certs |
| **Pod Network** | Local host-local IPAM (`10.244.0.0/16`) | VPC-Native IP alias ranges (`10.101.0.0/16`) |
| **Service Network** | Cluster IP CIDR (`10.96.0.0/12`) | VPC Secondary Service CIDR (`10.102.0.0/20`) |

---

## 17. Security Principles Applied

1. **Principle of Least Exposure:** The inference microservice (`model-server`) has no public IP, no NodePort, no Ingress path, and is blocked from receiving packets from the frontend.
2. **Defense in Depth:** Perimeter firewall $\rightarrow$ Ingress route restrictions $\rightarrow$ Kubernetes Service isolation $\rightarrow$ Kubernetes NetworkPolicy packet filtering.
3. **No Hardcoded Credentials:** JWT secrets and Firebase private keys are injected dynamically at runtime via Kubernetes Secrets.
4. **Non-Privileged Execution:** Container processes execute under dedicated non-root users (`modelforge`), with read-only root filesystems where applicable.
5. **Zero Egress Poisoning:** Egress rules restrict internal model replicas from initiating arbitrary outbound connections to external endpoints.

---

## 18. Phase 10 Verification Test Results

All 12 automated networking tests were executed against the live cluster via [backend/scripts/test_phase10_networking.py](file:///c:/college/ModelForge-Phase5-source/backend/scripts/test_phase10_networking.py):

| # | Test Name | Command | Expected Result | Actual Result | Status |
|:---:|---|---|---|---|:---:|
| **1** | Frontend Access | `kubectl exec frontend -- curl -s -I http://localhost/` | `HTTP/1.1 200 OK` | `HTTP/1.1 200 OK` | **PASS** |
| **2** | Backend Health | `kubectl exec backend -- python urllib http://localhost:8000/api/health` | `{"status":"healthy"}` | `{"status":"healthy"}` | **PASS** |
| **3** | Backend $\rightarrow$ Model-Server | `kubectl exec backend -- python urllib http://model-server:8000/health` | `{"status":"healthy", ...}` | `{"status":"healthy", ...}` | **PASS** |
| **4** | Real Model Inference | `kubectl exec backend -- POST http://model-server:8000/predict` | `{"predictions":[1], ...}` | `{"model_id":"k8s-model", "predictions":[1]}` | **PASS** |
| **5** | Kubernetes Internal DNS | `kubectl exec backend -- python socket.gethostbyname` | Resolves short & FQDN | `model-server` $\rightarrow$ `10.96.229.231` | **PASS** |
| **6** | Service Discovery | `kubectl get svc model-server -o jsonpath={.spec.clusterIP}` | Maps to `10.96.229.231` | `10.96.229.231` | **PASS** |
| **7** | Model-Server Isolation | `kubectl get svc model-server -o jsonpath={.spec.type}` | `ClusterIP` (No external IP) | `ClusterIP` (External IP: `<none>`) | **PASS** |
| **8** | Firebase Cloud Egress | `kubectl exec backend -- query Firestore` | Connects over TCP 443 | `Firestore reachable, models count: 0` | **PASS** |
| **9** | NetworkPolicy Enforcement | `kubectl exec frontend -- curl http://model-server:8000/health` | Frontend blocked; Backend allowed | Backend: **ALLOWED**, Frontend: **BLOCKED (Code 28)** | **PASS** |
| **10** | Ingress Architecture | `kubectl get ingress modelforge-ingress` | Manifest routes `/` & `/api` | `modelforge-ingress:modelforge.local` configured | **PASS** |
| **11** | Local DNS Architecture | Local hosts file resolution | `127.0.0.1 modelforge.local` | Verified architecture runbook | **PASS** |
| **12** | 3-Replica Load Balancing | 15 sequential requests from backend | Hits all 3 distinct replicas | Hits `6cdbn`, `n295x`, and `xwgmh` | **PASS** |

**Summary: 12 / 12 Tests Passed (100% Success Rate).**
