variable "kubeconfig_path" {
  type        = string
  description = "Path to local kubeconfig file"
  default     = "~/.kube/config"
}

variable "kube_context" {
  type        = string
  description = "Kubernetes context to target (must be docker-desktop for local-first execution)"
  default     = "docker-desktop"
}

variable "namespace" {
  type        = string
  description = "Target Kubernetes namespace for ModelForge platform"
  default     = "modelforge"
}

variable "environment" {
  type        = string
  description = "Deployment environment identifier (local, staging, production)"
  default     = "local"
}

variable "api_version" {
  type        = string
  description = "ModelForge platform software release version"
  default     = "1.5.0"
}

variable "model_storage_pvc_size" {
  type        = string
  description = "Storage capacity allocated for model cache PVC"
  default     = "1Gi"
}

variable "minio_pvc_size" {
  type        = string
  description = "Storage capacity allocated for MinIO object storage PVC"
  default     = "1Gi"
}

variable "registry_pvc_size" {
  type        = string
  description = "Storage capacity allocated for local Docker container registry PVC"
  default     = "2Gi"
}

variable "storage_class_name" {
  type        = string
  description = "StorageClass name for persistent volume claims"
  default     = "standard"
}
