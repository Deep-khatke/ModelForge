"""
Docker Container Engine for ModelForge Inference Replicas.

Manages isolated Docker containers for model inference replicas, performs real
HTTP health checks, routes prediction requests, and handles graceful fallback
when Docker is unavailable or disabled.
"""
from __future__ import annotations

import logging
import socket
from pathlib import Path
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger("modelforge.container_engine")

try:
    import docker
    from docker.errors import APIError, DockerException, NotFound
except ImportError:
    docker = None  # type: ignore
    DockerException = Exception  # type: ignore
    APIError = Exception  # type: ignore
    NotFound = Exception  # type: ignore


def is_docker_available() -> bool:
    """Check if Docker is enabled in settings and the Docker daemon is reachable."""
    if not settings.docker_enabled:
        return False
    if docker is None:
        return False
    try:
        client = docker.from_env()
        return bool(client.ping())
    except Exception as exc:
        logger.warning("Docker daemon check failed: %s", exc)
        return False


def get_docker_client():
    """Return a Docker client instance if Docker is enabled and available, else None."""
    if not is_docker_available():
        return None
    try:
        return docker.from_env()
    except Exception:
        return None


def find_free_port(start_port: int = 8100, max_tries: int = 100) -> int:
    """Find an available local TCP port on the host."""
    for port in range(start_port, start_port + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start_port


class ContainerManager:
    """Manages Docker containers for ModelForge inference replicas."""

    def __init__(self, client=None):
        self._client = client

    @property
    def client(self):
        if self._client is None:
            self._client = get_docker_client()
        return self._client

    def is_available(self) -> bool:
        return is_docker_available()

    def start_replica_container(
        self,
        deployment_id: str,
        replica_id: str,
        model_id: str,
        version_label: str,
        file_path: str,
    ) -> dict[str, Any]:
        """
        Start an isolated inference replica container.

        Returns a dictionary with container metadata:
        - container_id: str
        - container_port: int | None
        - endpoint_url: str
        - status: str ('healthy' or 'unhealthy')
        """
        cli = self.client
        if cli is None:
            raise RuntimeError("Docker client is unavailable")

        # Sanitize container name
        safe_dep_id = deployment_id[:12].replace("-", "")
        safe_rep_id = replica_id.replace("_", "-")
        container_name = f"modelforge-rep-{safe_dep_id}-{safe_rep_id}"

        # Clean up any existing container with the same name
        try:
            old_c = cli.containers.get(container_name)
            old_c.stop(timeout=2)
            old_c.remove(v=True, force=True)
        except Exception:
            pass

        # Calculate container-relative model path
        try:
            rel_path = Path(file_path).relative_to(settings.model_storage_path)
            container_model_path = f"/models/{rel_path.as_posix()}"
        except ValueError:
            container_model_path = f"/models/{Path(file_path).name}"

        # Setup volume mount (read-only to protect model artifacts)
        mount_source = settings.model_storage_mount or str(settings.model_storage_path)
        volumes = {
            mount_source: {
                "bind": "/models",
                "mode": "ro",
            }
        }

        # Allocate host port for host-level connectivity
        host_port = find_free_port(settings.container_port_start)
        ports = {"8000/tcp": host_port}

        env = {
            "MODEL_PATH": container_model_path,
            "REPLICA_ID": replica_id,
            "DEPLOYMENT_ID": deployment_id,
            "MODEL_ID": model_id,
            "MODEL_VERSION": version_label,
        }

        labels = {
            "modelforge.managed": "true",
            "modelforge.deployment_id": deployment_id,
            "modelforge.replica_id": replica_id,
        }

        # Start container
        try:
            container = cli.containers.run(
                image=settings.inference_image,
                name=container_name,
                detach=True,
                environment=env,
                volumes=volumes,
                ports=ports,
                network=settings.docker_network if settings.docker_network else None,
                labels=labels,
                restart_policy={"Name": "on-failure", "MaximumRetryCount": 3},
            )
        except Exception as exc:
            logger.error("Failed to run replica container %s: %s", container_name, exc)
            raise RuntimeError(f"Failed to start replica container: {exc}") from exc

        # Determine endpoint URL
        endpoint_url = f"http://127.0.0.1:{host_port}"

        # Verify container health
        is_healthy = self.wait_for_health(endpoint_url, timeout=settings.container_healthcheck_timeout_sec)

        return {
            "container_id": container.id,
            "container_name": container_name,
            "container_port": host_port,
            "endpoint_url": endpoint_url,
            "status": "healthy" if is_healthy else "unhealthy",
        }

    def wait_for_health(self, endpoint_url: str, timeout: float = 5.0) -> bool:
        """Poll container's /health endpoint until it responds healthy or times out."""
        import time

        deadline = time.perf_counter() + timeout
        health_url = f"{endpoint_url}/health"

        while time.perf_counter() < deadline:
            try:
                resp = httpx.get(health_url, timeout=1.0)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("status") == "healthy":
                        return True
            except Exception:
                pass
            time.sleep(0.3)

        return False

    def check_replica_health(self, endpoint_url: str, timeout: float = 2.0) -> bool:
        """Single check against a replica's /health endpoint."""
        try:
            resp = httpx.get(f"{endpoint_url}/health", timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("status") == "healthy"
        except Exception:
            return False
        return False

    def stop_replica_container(self, container_id: str | None) -> None:
        """Stop and remove a replica container cleanly."""
        if not container_id:
            return
        cli = self.client
        if cli is None:
            return
        try:
            container = cli.containers.get(container_id)
            container.stop(timeout=3)
            container.remove(v=True, force=True)
        except Exception as exc:
            logger.warning("Error stopping container %s: %s", container_id, exc)

    def stop_deployment_containers(self, deployment_id: str) -> None:
        """Stop all containers belonging to a deployment by label."""
        cli = self.client
        if cli is None:
            return
        try:
            containers = cli.containers.list(
                all=True,
                filters={"label": f"modelforge.deployment_id={deployment_id}"},
            )
            for c in containers:
                try:
                    c.stop(timeout=2)
                    c.remove(v=True, force=True)
                except Exception:
                    pass
        except Exception as exc:
            logger.warning("Error stopping deployment containers for %s: %s", deployment_id, exc)

    def predict_container(
        self,
        endpoint_url: str,
        features: list[Any],
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """Send an inference request to a container replica."""
        url = f"{endpoint_url}/predict"
        try:
            resp = httpx.post(url, json={"features": features}, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            logger.error("Replica returned error %s: %s", exc.response.status_code, exc.response.text)
            raise RuntimeError(f"Replica inference error: {exc.response.text}") from exc
        except Exception as exc:
            logger.error("Failed to query replica at %s: %s", url, exc)
            raise RuntimeError(f"Replica communication error: {exc}") from exc


container_manager = ContainerManager()
