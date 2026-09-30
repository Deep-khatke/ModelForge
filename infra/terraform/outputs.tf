output "namespace" {
  description = "Target Kubernetes namespace name"
  value       = kubernetes_namespace.modelforge.metadata[0].name
}

output "environment" {
  description = "Target infrastructure environment"
  value       = var.environment
}

output "configmap_name" {
  description = "Name of the provisioned application ConfigMap"
  value       = kubernetes_config_map.modelforge_config.metadata[0].name
}

output "model_storage_pvc" {
  description = "Claim name for shared model artifacts"
  value       = kubernetes_persistent_volume_claim.model_storage.metadata[0].name
}

output "minio_pvc" {
  description = "Claim name for MinIO S3 object storage"
  value       = kubernetes_persistent_volume_claim.minio_storage.metadata[0].name
}

output "registry_pvc" {
  description = "Claim name for private Docker container registry"
  value       = kubernetes_persistent_volume_claim.registry_storage.metadata[0].name
}

output "backend_service_account" {
  description = "IAM ServiceAccount for backend control plane"
  value       = kubernetes_service_account.backend.metadata[0].name
}

output "frontend_service_account" {
  description = "IAM ServiceAccount for frontend dashboard"
  value       = kubernetes_service_account.frontend.metadata[0].name
}

output "model_server_service_account" {
  description = "IAM ServiceAccount for inference pods"
  value       = kubernetes_service_account.model_server.metadata[0].name
}
