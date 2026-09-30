terraform {
  required_version = ">= 1.6.0"

  required_providers {
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.35.0"
    }
  }

  # Local state storage - no cloud backends or paid SaaS
  backend "local" {
    path = "terraform.tfstate"
  }
}
