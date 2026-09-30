const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
const TOKEN_KEY = "modelforge_auth_token";

export function getAuthToken() {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setAuthToken(token) {
  try {
    if (token) {
      localStorage.setItem(TOKEN_KEY, token);
    } else {
      localStorage.removeItem(TOKEN_KEY);
    }
  } catch {
    // localStorage may be disabled or restricted
  }
}

export function clearAuthToken() {
  try {
    localStorage.removeItem(TOKEN_KEY);
  } catch {
    // ignore
  }
}

function getHeaders(extraHeaders = {}) {
  const headers = { ...extraHeaders };
  const token = getAuthToken();
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  return headers;
}

function getAuthOnlyHeaders() {
  const headers = {};
  const token = getAuthToken();
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  return headers;
}

async function handleResponse(res) {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      // response wasn't JSON; fall back to statusText
    }
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  return res.json();
}

// --- Authentication & User Endpoints (Phase 8) -------------------------------

export async function loginUser(email, password) {
  const res = await fetch(`${API_BASE_URL}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  const data = await handleResponse(res);
  if (data && data.access_token) {
    setAuthToken(data.access_token);
  }
  return data;
}

export async function registerUser(email, password, displayName) {
  const res = await fetch(`${API_BASE_URL}/api/v1/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      email,
      password,
      display_name: displayName,
    }),
  });
  const data = await handleResponse(res);
  if (data && data.access_token) {
    setAuthToken(data.access_token);
  }
  return data;
}

export async function fetchCurrentUser() {
  const res = await fetch(`${API_BASE_URL}/api/v1/auth/me`, {
    headers: getHeaders(),
  });
  return handleResponse(res);
}

export async function logoutUser() {
  try {
    await fetch(`${API_BASE_URL}/api/v1/auth/logout`, {
      method: "POST",
      headers: getHeaders(),
    });
  } finally {
    clearAuthToken();
  }
}

export async function fetchUsers() {
  const res = await fetch(`${API_BASE_URL}/api/v1/users`, {
    headers: getHeaders(),
  });
  return handleResponse(res);
}

export async function createUser({ email, password, displayName, role = "VIEWER" }) {
  const res = await fetch(`${API_BASE_URL}/api/v1/users`, {
    method: "POST",
    headers: getHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({
      email,
      password,
      display_name: displayName,
      role,
    }),
  });
  return handleResponse(res);
}

export async function updateUser(userId, data) {
  const res = await fetch(`${API_BASE_URL}/api/v1/users/${userId}`, {
    method: "PUT",
    headers: getHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(data),
  });
  return handleResponse(res);
}

export async function deleteUser(userId) {
  const res = await fetch(`${API_BASE_URL}/api/v1/users/${userId}`, {
    method: "DELETE",
    headers: getHeaders(),
  });
  return handleResponse(res);
}

// --- Audit Log Endpoints (Phase 8) -------------------------------------------

export async function fetchAuditEvents({
  action = null,
  resourceType = null,
  userId = null,
  success = null,
  limit = 50,
  offset = 0,
} = {}) {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (action) query.append("action", action);
  if (resourceType) query.append("resource_type", resourceType);
  if (userId) query.append("user_id", userId);
  if (success !== null && success !== undefined && success !== "") {
    query.append("success", String(success));
  }
  const res = await fetch(`${API_BASE_URL}/api/v1/audit/events?${query.toString()}`, {
    headers: getHeaders(),
  });
  return handleResponse(res);
}

export function getAuditExportUrl({
  action = null,
  resourceType = null,
  userId = null,
  success = null,
} = {}) {
  const query = new URLSearchParams();
  const token = getAuthToken();
  if (token) query.append("token", token);
  if (action) query.append("action", action);
  if (resourceType) query.append("resource_type", resourceType);
  if (userId) query.append("user_id", userId);
  if (success !== null && success !== undefined && success !== "") {
    query.append("success", String(success));
  }
  return `${API_BASE_URL}/api/v1/audit/export?${query.toString()}`;
}

// --- Models Endpoints --------------------------------------------------------

export async function fetchModels() {
  const res = await fetch(`${API_BASE_URL}/api/v1/models`, {
    headers: getHeaders(),
  });
  return handleResponse(res);
}

export async function fetchModel(modelId) {
  const res = await fetch(`${API_BASE_URL}/api/v1/models/${modelId}`, {
    headers: getHeaders(),
  });
  return handleResponse(res);
}

export async function uploadModel({ modelName, framework, file }) {
  const formData = new FormData();
  formData.append("model_name", modelName);
  formData.append("framework", framework || "sklearn");
  formData.append("file", file);

  const res = await fetch(`${API_BASE_URL}/api/v1/models/upload`, {
    method: "POST",
    headers: getAuthOnlyHeaders(),
    body: formData,
  });
  return handleResponse(res);
}

export async function activateVersion(modelId, version) {
  const res = await fetch(
    `${API_BASE_URL}/api/v1/models/${modelId}/versions/${version}/activate`,
    {
      method: "POST",
      headers: getHeaders(),
    }
  );
  return handleResponse(res);
}

export async function deleteModel(modelId) {
  const res = await fetch(`${API_BASE_URL}/api/v1/models/${modelId}`, {
    method: "DELETE",
    headers: getHeaders(),
  });
  return handleResponse(res);
}

export async function checkApiHealth() {
  const res = await fetch(`${API_BASE_URL}/api/health`);
  return handleResponse(res);
}

// --- Deployments Endpoints ---------------------------------------------------

export async function createDeployment({ modelId, version, replicas }) {
  const res = await fetch(`${API_BASE_URL}/api/v1/deployments`, {
    method: "POST",
    headers: getHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({
      model_id: modelId,
      version: version || null,
      replicas: replicas || 1,
    }),
  });
  return handleResponse(res);
}

export async function fetchDeployments() {
  const res = await fetch(`${API_BASE_URL}/api/v1/deployments`, {
    headers: getHeaders(),
  });
  return handleResponse(res);
}

export async function stopDeployment(deploymentId) {
  const res = await fetch(
    `${API_BASE_URL}/api/v1/deployments/${deploymentId}/stop`,
    {
      method: "POST",
      headers: getHeaders(),
    }
  );
  return handleResponse(res);
}

export async function deleteDeployment(deploymentId) {
  const res = await fetch(`${API_BASE_URL}/api/v1/deployments/${deploymentId}`, {
    method: "DELETE",
    headers: getHeaders(),
  });
  return handleResponse(res);
}

export async function predictModel(modelId, features) {
  const res = await fetch(`${API_BASE_URL}/api/v1/models/${modelId}/predict`, {
    method: "POST",
    headers: getHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ features }),
  });
  return handleResponse(res);
}

export async function scaleDeployment(deploymentId, replicas) {
  const res = await fetch(`${API_BASE_URL}/api/v1/deployments/${deploymentId}/scale`, {
    method: "POST",
    headers: getHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ replicas }),
  });
  return handleResponse(res);
}

export async function fetchDeploymentReplicas(deploymentId) {
  const res = await fetch(`${API_BASE_URL}/api/v1/deployments/${deploymentId}/replicas`, {
    headers: getHeaders(),
  });
  return handleResponse(res);
}

export async function runLoadTest(deploymentId, requests = 20, features = null) {
  const res = await fetch(`${API_BASE_URL}/api/v1/deployments/${deploymentId}/load-test`, {
    method: "POST",
    headers: getHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ requests, features }),
  });
  return handleResponse(res);
}

export async function fetchInferenceLogs(deploymentId) {
  const res = await fetch(`${API_BASE_URL}/api/v1/deployments/${deploymentId}/logs`, {
    headers: getHeaders(),
  });
  return handleResponse(res);
}

// --- Phase 5: Monitoring & Performance Analytics ----------------------------

export async function fetchMonitoringSummary(timeRange = "1h") {
  const res = await fetch(`${API_BASE_URL}/api/v1/monitoring/summary?range=${timeRange}`, {
    headers: getHeaders(),
  });
  return handleResponse(res);
}

export async function fetchDeploymentMetrics(deploymentId, timeRange = "1h") {
  const res = await fetch(`${API_BASE_URL}/api/v1/monitoring/deployments/${deploymentId}?range=${timeRange}`, {
    headers: getHeaders(),
  });
  return handleResponse(res);
}

export async function fetchModelMetrics(modelId, timeRange = "1h") {
  const res = await fetch(`${API_BASE_URL}/api/v1/monitoring/models/${modelId}?range=${timeRange}`, {
    headers: getHeaders(),
  });
  return handleResponse(res);
}

export async function fetchMonitoringDeployments(timeRange = "1h") {
  const res = await fetch(`${API_BASE_URL}/api/v1/monitoring/deployments?range=${timeRange}`, {
    headers: getHeaders(),
  });
  return handleResponse(res);
}

export async function fetchMonitoringReplicas(deploymentId, timeRange = "1h") {
  const res = await fetch(`${API_BASE_URL}/api/v1/monitoring/deployments/${deploymentId}/replicas?range=${timeRange}`, {
    headers: getHeaders(),
  });
  return handleResponse(res);
}

export async function fetchMonitoringTimeseries(timeRange = "1h", deploymentId = null) {
  const query = new URLSearchParams({ range: timeRange });
  if (deploymentId) query.append("deployment_id", deploymentId);
  const res = await fetch(`${API_BASE_URL}/api/v1/monitoring/timeseries?${query.toString()}`, {
    headers: getHeaders(),
  });
  return handleResponse(res);
}

export async function fetchSystemMetrics() {
  const res = await fetch(`${API_BASE_URL}/api/v1/monitoring/system`, {
    headers: getHeaders(),
  });
  return handleResponse(res);
}

export async function fetchMonitoringAlerts(timeRange = "1h") {
  const res = await fetch(`${API_BASE_URL}/api/v1/monitoring/alerts?range=${timeRange}`, {
    headers: getHeaders(),
  });
  return handleResponse(res);
}

export function getMonitoringExportUrl(timeRange = "1h", deploymentId = null) {
  const query = new URLSearchParams({ range: timeRange });
  if (deploymentId) query.append("deployment_id", deploymentId);
  return `${API_BASE_URL}/api/v1/monitoring/export?${query.toString()}`;
}

export async function fetchRecentInferences(timeRange = "1h", deploymentId = null, limit = 25, offset = 0) {
  const query = new URLSearchParams({ range: timeRange, limit: String(limit), offset: String(offset) });
  if (deploymentId) query.append("deployment_id", deploymentId);
  const res = await fetch(`${API_BASE_URL}/api/v1/monitoring/requests/recent?${query.toString()}`, {
    headers: getHeaders(),
  });
  return handleResponse(res);
}

export async function runExperiment({ deploymentId, requests = 100, features = null }) {
  const res = await fetch(`${API_BASE_URL}/api/v1/experiments/run`, {
    method: "POST",
    headers: getHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({
      deployment_id: deploymentId,
      requests,
      features,
    }),
  });
  return handleResponse(res);
}

export async function fetchExperiments() {
  const res = await fetch(`${API_BASE_URL}/api/v1/experiments`, {
    headers: getHeaders(),
  });
  return handleResponse(res);
}

export function getExperimentsExportUrl() {
  return `${API_BASE_URL}/api/v1/experiments/export`;
}

// --- Auto-Scaling Endpoints (Phase 7) ---------------------------------------

export async function fetchAutoScalingConfig(deploymentId) {
  const res = await fetch(`${API_BASE_URL}/api/v1/deployments/${deploymentId}/autoscaling`, {
    headers: getHeaders(),
  });
  return handleResponse(res);
}

export async function updateAutoScalingConfig(deploymentId, config) {
  const res = await fetch(`${API_BASE_URL}/api/v1/deployments/${deploymentId}/autoscaling`, {
    method: "PUT",
    headers: getHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(config),
  });
  return handleResponse(res);
}

export async function evaluateAutoScaling(deploymentId) {
  const res = await fetch(
    `${API_BASE_URL}/api/v1/deployments/${deploymentId}/autoscaling/evaluate`,
    {
      method: "POST",
      headers: getHeaders(),
    }
  );
  return handleResponse(res);
}

export async function fetchScalingEvents(deploymentId) {
  const res = await fetch(`${API_BASE_URL}/api/v1/deployments/${deploymentId}/scaling-events`, {
    headers: getHeaders(),
  });
  return handleResponse(res);
}

export async function evaluateSystemAutoScaling() {
  const res = await fetch(`${API_BASE_URL}/api/v1/autoscaling/evaluate`, {
    method: "POST",
    headers: getHeaders(),
  });
  return handleResponse(res);
}
