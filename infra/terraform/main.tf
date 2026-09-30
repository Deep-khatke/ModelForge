# ModelForge Phase 15 — Infrastructure as Code (OpenTofu)
# Local-First, Zero-Cost Kubernetes Infrastructure Definition

provider "kubernetes" {
  config_path    = pathexpand(var.kubeconfig_path)
  config_context = var.kube_context
}

# 1. Namespace
resource "kubernetes_namespace" "modelforge" {
  metadata {
    name = var.namespace
    labels = {
      "app.kubernetes.io/name" = "modelforge"
      "environment"            = var.environment
      "managed-by"             = "opentofu"
    }
  }
}

# 2. Application ConfigMap
resource "kubernetes_config_map" "modelforge_config" {
  metadata {
    name      = "modelforge-config"
    namespace = kubernetes_namespace.modelforge.metadata[0].name
    labels = {
      "app.kubernetes.io/name"      = "modelforge"
      "app.kubernetes.io/component" = "config"
      "managed-by"                  = "opentofu"
    }
  }

  data = {
    DATABASE_BACKEND                   = "firestore"
    DATABASE_URL                       = "sqlite:////app/storage/models/modelforge.db"
    FIREBASE_PROJECT_ID                = "modelforge-d8cd0"
    FIREBASE_AUTH_ENABLED              = "true"
    GOOGLE_APPLICATION_CREDENTIALS     = "/etc/modelforge/credentials/firebase-credentials.json"
    MODEL_STORAGE_DIR                  = "/app/storage/models"
    MAX_UPLOAD_SIZE_MB                 = "50"
    ALLOWED_MODEL_EXTENSIONS           = ".joblib"
    CORS_ORIGINS                       = "http://localhost:5173,http://127.0.0.1:5173,http://localhost,http://127.0.0.1,http://172.18.0.2,http://modelforge.local"
    API_TITLE                          = "ModelForge API"
    API_VERSION                        = var.api_version
    MAX_REPLICAS                       = "5"
    DEFAULT_REPLICAS                   = "1"
    ALERT_LATENCY_THRESHOLD_MS         = "500.0"
    ALERT_ERROR_RATE_THRESHOLD_PERCENT = "5.0"
    MONITORING_RETENTION_DAYS          = "30"
    MODEL_SERVER_URL                   = "http://model-server.modelforge.svc.cluster.local:8000"
    MODEL_STORAGE_BACKEND              = "minio"
    MINIO_ENDPOINT                     = "http://minio.modelforge.svc.cluster.local:9000"
    MINIO_BUCKET                       = "modelforge-models"
  }
}

# 3. Persistent Volume Claims (Storage & Registry)
resource "kubernetes_persistent_volume_claim" "model_storage" {
  metadata {
    name      = "modelforge-model-storage-pvc"
    namespace = kubernetes_namespace.modelforge.metadata[0].name
    labels = {
      "app.kubernetes.io/name"      = "modelforge"
      "app.kubernetes.io/component" = "storage"
      "managed-by"                  = "opentofu"
    }
  }

  spec {
    access_modes       = ["ReadWriteOnce"]
    storage_class_name = var.storage_class_name
    resources {
      requests = {
        storage = var.model_storage_pvc_size
      }
    }
  }
}

resource "kubernetes_persistent_volume_claim" "minio_storage" {
  metadata {
    name      = "minio-pvc"
    namespace = kubernetes_namespace.modelforge.metadata[0].name
    labels = {
      "app.kubernetes.io/name"      = "modelforge"
      "app.kubernetes.io/component" = "minio"
      "managed-by"                  = "opentofu"
    }
  }

  spec {
    access_modes       = ["ReadWriteOnce"]
    storage_class_name = var.storage_class_name
    resources {
      requests = {
        storage = var.minio_pvc_size
      }
    }
  }
}

resource "kubernetes_persistent_volume_claim" "registry_storage" {
  metadata {
    name      = "registry-pvc"
    namespace = kubernetes_namespace.modelforge.metadata[0].name
    labels = {
      "app.kubernetes.io/name"      = "modelforge"
      "app.kubernetes.io/component" = "registry"
      "managed-by"                  = "opentofu"
    }
  }

  spec {
    access_modes       = ["ReadWriteOnce"]
    storage_class_name = var.storage_class_name
    resources {
      requests = {
        storage = var.registry_pvc_size
      }
    }
  }
}

# 4. Service Accounts (Least-Privilege IAM)
resource "kubernetes_service_account" "backend" {
  metadata {
    name      = "modelforge-backend"
    namespace = kubernetes_namespace.modelforge.metadata[0].name
    labels = {
      "app.kubernetes.io/name"      = "modelforge"
      "app.kubernetes.io/component" = "backend"
      "managed-by"                  = "opentofu"
    }
  }
  automount_service_account_token = true
}

resource "kubernetes_service_account" "frontend" {
  metadata {
    name      = "modelforge-frontend"
    namespace = kubernetes_namespace.modelforge.metadata[0].name
    labels = {
      "app.kubernetes.io/name"      = "modelforge"
      "app.kubernetes.io/component" = "frontend"
      "managed-by"                  = "opentofu"
    }
  }
  automount_service_account_token = false
}

resource "kubernetes_service_account" "model_server" {
  metadata {
    name      = "modelforge-model-server"
    namespace = kubernetes_namespace.modelforge.metadata[0].name
    labels = {
      "app.kubernetes.io/name"      = "modelforge"
      "app.kubernetes.io/component" = "model-server"
      "managed-by"                  = "opentofu"
    }
  }
  automount_service_account_token = false
}

# 5. Kubernetes RBAC (Role & RoleBinding for Backend)
resource "kubernetes_role" "backend_role" {
  metadata {
    name      = "modelforge-backend-role"
    namespace = kubernetes_namespace.modelforge.metadata[0].name
    labels = {
      "app.kubernetes.io/name"      = "modelforge"
      "app.kubernetes.io/component" = "backend"
      "managed-by"                  = "opentofu"
    }
  }

  rule {
    api_groups = ["apps"]
    resources  = ["deployments"]
    verbs      = ["get", "list", "watch", "create", "update", "patch", "delete"]
  }

  rule {
    api_groups = [""]
    resources  = ["services"]
    verbs      = ["get", "list", "watch", "create", "update", "patch", "delete"]
  }

  rule {
    api_groups = [""]
    resources  = ["pods", "configmaps"]
    verbs      = ["get", "list", "watch"]
  }

  rule {
    api_groups = ["autoscaling"]
    resources  = ["horizontalpodautoscalers"]
    verbs      = ["get", "list", "watch"]
  }
}

resource "kubernetes_role_binding" "backend_rolebinding" {
  metadata {
    name      = "modelforge-backend-rolebinding"
    namespace = kubernetes_namespace.modelforge.metadata[0].name
    labels = {
      "app.kubernetes.io/name"      = "modelforge"
      "app.kubernetes.io/component" = "backend"
      "managed-by"                  = "opentofu"
    }
  }

  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "Role"
    name      = kubernetes_role.backend_role.metadata[0].name
  }

  subject {
    kind      = "ServiceAccount"
    name      = kubernetes_service_account.backend.metadata[0].name
    namespace = kubernetes_namespace.modelforge.metadata[0].name
  }
}
