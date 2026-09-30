import { useCallback, useEffect, useState } from "react";
import { fetchCurrentUser, fetchDeployments, fetchModels, logoutUser } from "../api/client";
import AuditLogViewer from "./AuditLogViewer";
import AutoScalingDashboard from "./AutoScalingDashboard";
import DeploymentList from "./DeploymentList";
import InferencePanel from "./InferencePanel";
import LoadBalancingSection from "./LoadBalancingSection";
import LoginModal from "./LoginModal";
import ModelList from "./ModelList";
import MonitoringDashboard from "./MonitoringDashboard";
import PerformanceExperiments from "./PerformanceExperiments";
import ReplicaManagerCard from "./ReplicaManagerCard";
import UploadModel from "./UploadModel";
import UserManagement from "./UserManagement";

export default function Dashboard() {
  const [activeTab, setActiveTab] = useState("overview");

  // Authentication state
  const [currentUser, setCurrentUser] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [isLoginModalOpen, setIsLoginModalOpen] = useState(false);

  const [models, setModels] = useState([]);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [modelsError, setModelsError] = useState(null);

  const [deployments, setDeployments] = useState([]);
  const [deploymentsLoading, setDeploymentsLoading] = useState(true);
  const [deploymentsError, setDeploymentsError] = useState(null);

  const [inferenceCount, setInferenceCount] = useState(0);

  const loadUser = useCallback(async () => {
    setAuthLoading(true);
    try {
      const user = await fetchCurrentUser();
      setCurrentUser(user);
    } catch {
      setCurrentUser(null);
    } finally {
      setAuthLoading(false);
    }
  }, []);

  const loadModels = useCallback(async () => {
    setModelsLoading(true);
    setModelsError(null);
    try {
      const data = await fetchModels();
      setModels(data);
    } catch (err) {
      setModelsError(err.message);
    } finally {
      setModelsLoading(false);
    }
  }, []);

  const loadDeployments = useCallback(async () => {
    setDeploymentsLoading(true);
    setDeploymentsError(null);
    try {
      const data = await fetchDeployments();
      setDeployments(data);
    } catch (err) {
      setDeploymentsError(err.message);
    } finally {
      setDeploymentsLoading(false);
    }
  }, []);

  const refreshAll = useCallback(() => {
    loadModels();
    loadDeployments();
  }, [loadModels, loadDeployments]);

  useEffect(() => {
    loadUser();
    refreshAll();
  }, [loadUser, refreshAll]);

  async function handleLogout() {
    await logoutUser();
    setCurrentUser(null);
    loadUser();
    refreshAll();
  }

  const role = currentUser?.role || "ADMIN"; // Default to dev admin if unauthenticated dev mode
  const isAdmin = role === "ADMIN";
  const isOperator = role === "OPERATOR";
  const isViewer = role === "VIEWER";
  const canMutate = isAdmin || isOperator;

  const totalVersions = models.reduce((sum, m) => sum + m.versions.length, 0);
  const activeDeployments = deployments.filter((d) => d.status === "running");
  const runningDeployment = activeDeployments.length > 0 ? activeDeployments[0] : null;

  const roleBadges = {
    ADMIN: "bg-purple-100 text-purple-800 border-purple-200",
    OPERATOR: "bg-blue-100 text-blue-800 border-blue-200",
    VIEWER: "bg-slate-100 text-slate-700 border-slate-200",
  };

  return (
    <div className="max-w-7xl mx-auto px-4 py-8 space-y-8">
      {/* Top Header */}
      <header className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-200 pb-5">
        <div>
          <h1 className="text-2xl font-extrabold text-slate-900 tracking-tight flex items-center gap-2">
            ModelForge
            <span className="text-xs bg-indigo-100 text-indigo-800 font-semibold px-2.5 py-0.5 rounded-full uppercase">
              Phase 8: Auth, RBAC &amp; Audit
            </span>
          </h1>
          <p className="text-slate-500 text-sm mt-0.5">
            Cloud-Ready ML Platform: Registry, Multi-Replica Containers, Load Balancing, Telemetry, Auto-Scaling &amp; RBAC Security
          </p>
        </div>

        {/* User Profile & Auth Controls */}
        <div className="flex items-center space-x-3">
          {currentUser ? (
            <div className="flex items-center space-x-3 bg-slate-50 border border-slate-200 rounded-xl px-3.5 py-2">
              <div className="text-right">
                <div className="text-xs font-bold text-slate-900 flex items-center gap-1.5 justify-end">
                  <span>{currentUser.display_name}</span>
                  <span
                    className={`text-[10px] uppercase font-extrabold px-1.5 py-0.5 rounded border ${
                      roleBadges[currentUser.role] || roleBadges.VIEWER
                    }`}
                  >
                    {currentUser.role}
                  </span>
                </div>
                <div className="text-[11px] text-slate-500">{currentUser.email}</div>
              </div>
              <button
                type="button"
                onClick={handleLogout}
                className="text-xs text-slate-600 hover:text-slate-900 font-medium px-2.5 py-1 bg-white border border-slate-200 rounded-lg hover:bg-slate-100 transition shadow-2xs"
              >
                Sign Out
              </button>
            </div>
          ) : (
            <div className="flex items-center space-x-2">
              <span className="text-xs text-slate-500 hidden sm:inline">Local Dev Mode</span>
              <button
                type="button"
                onClick={() => setIsLoginModalOpen(true)}
                className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-semibold rounded-lg shadow-sm transition flex items-center space-x-1.5"
              >
                <span>🔑</span>
                <span>Sign In / Switch User</span>
              </button>
            </div>
          )}
        </div>
      </header>

      {/* Viewer Role Notice Banner */}
      {isViewer && (
        <div className="p-3.5 bg-amber-50 border border-amber-200 text-amber-800 rounded-xl text-xs flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <span className="text-base font-bold">ℹ</span>
            <span>
              <strong>Viewer Mode Active:</strong> You have read-only access to models, deployments, and inference. Deployment, scaling, and upload actions are restricted to Operator and Admin roles.
            </span>
          </div>
          <button
            onClick={() => setIsLoginModalOpen(true)}
            className="font-semibold underline hover:text-amber-950"
          >
            Switch Account
          </button>
        </div>
      )}

      {/* Tab Navigation */}
      <div className="flex justify-between items-center border-b border-slate-200 pb-2">
        <div className="inline-flex rounded-xl bg-slate-100 p-1 border border-slate-200 shadow-inner flex-wrap gap-1">
          <button
            onClick={() => setActiveTab("overview")}
            className={`px-4 py-2 text-xs font-bold rounded-lg transition-all ${
              activeTab === "overview"
                ? "bg-white text-indigo-700 shadow-sm"
                : "text-slate-600 hover:text-slate-900"
            }`}
          >
            Overview &amp; Models
          </button>
          <button
            onClick={() => setActiveTab("autoscaling")}
            className={`px-4 py-2 text-xs font-bold rounded-lg transition-all flex items-center gap-1.5 ${
              activeTab === "autoscaling"
                ? "bg-white text-indigo-700 shadow-sm"
                : "text-slate-600 hover:text-slate-900"
            }`}
          >
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-blue-500"></span>
            </span>
            Auto-Scaling &amp; Reliability
          </button>
          <button
            onClick={() => setActiveTab("monitoring")}
            className={`px-4 py-2 text-xs font-bold rounded-lg transition-all flex items-center gap-1.5 ${
              activeTab === "monitoring"
                ? "bg-white text-indigo-700 shadow-sm"
                : "text-slate-600 hover:text-slate-900"
            }`}
          >
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
            </span>
            Monitoring &amp; Telemetry
          </button>
          <button
            onClick={() => setActiveTab("experiments")}
            className={`px-4 py-2 text-xs font-bold rounded-lg transition-all ${
              activeTab === "experiments"
                ? "bg-white text-indigo-700 shadow-sm"
                : "text-slate-600 hover:text-slate-900"
            }`}
          >
            Performance Experiments
          </button>

          {/* Admin-only Tabs */}
          {isAdmin && (
            <>
              <button
                onClick={() => setActiveTab("users")}
                className={`px-4 py-2 text-xs font-bold rounded-lg transition-all flex items-center gap-1.5 ${
                  activeTab === "users"
                    ? "bg-white text-purple-700 shadow-sm"
                    : "text-purple-700 hover:text-purple-900"
                }`}
              >
                <span>👥</span>
                <span>User Management</span>
              </button>
              <button
                onClick={() => setActiveTab("audit")}
                className={`px-4 py-2 text-xs font-bold rounded-lg transition-all flex items-center gap-1.5 ${
                  activeTab === "audit"
                    ? "bg-white text-purple-700 shadow-sm"
                    : "text-purple-700 hover:text-purple-900"
                }`}
              >
                <span>🛡️</span>
                <span>Audit Logs</span>
              </button>
            </>
          )}
        </div>
      </div>

      {/* Overview Tab Content */}
      {activeTab === "overview" && (
        <div className="space-y-8">
          <section className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <StatCard label="Registered models" value={models.length} />
            <StatCard label="Total versions" value={totalVersions} />
            <StatCard label="Active deployments" value={activeDeployments.length} />
            <StatCard label="Inference requests" value={inferenceCount} hint="Session total" />
          </section>

          {runningDeployment && (
            <>
              <ReplicaManagerCard
                deployment={runningDeployment}
                onChanged={refreshAll}
                disabled={!canMutate}
              />
              <LoadBalancingSection
                deployment={runningDeployment}
                onInferenceRan={() => setInferenceCount((prev) => prev + 1)}
              />
            </>
          )}

          <div>
            <InferencePanel
              models={models}
              deployments={deployments}
              onRequestExecuted={() => setInferenceCount((prev) => prev + 1)}
            />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2">
              <h2 className="text-lg font-semibold mb-3">Models</h2>
              <ModelList
                models={models}
                loading={modelsLoading}
                error={modelsError}
                onChanged={refreshAll}
                disabled={!canMutate}
              />
            </div>
            <div>
              {canMutate ? (
                <UploadModel onUploaded={refreshAll} />
              ) : (
                <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm text-center">
                  <div className="text-2xl mb-2">🔒</div>
                  <h3 className="text-sm font-semibold text-slate-800">Upload Restricted</h3>
                  <p className="text-xs text-slate-500 mt-1">
                    Uploading new model weights requires Operator or Admin privileges.
                  </p>
                </div>
              )}
            </div>
          </div>

          <div>
            <h2 className="text-lg font-semibold mb-3">Deployments</h2>
            <DeploymentList
              deployments={deployments}
              loading={deploymentsLoading}
              error={deploymentsError}
              onChanged={refreshAll}
              disabled={!canMutate}
            />
          </div>
        </div>
      )}

      {/* Auto-Scaling Tab Content */}
      {activeTab === "autoscaling" && (
        <AutoScalingDashboard
          deployments={deployments}
          onDeploymentChanged={refreshAll}
          disabled={!canMutate}
        />
      )}

      {/* Monitoring Tab Content */}
      {activeTab === "monitoring" && <MonitoringDashboard />}

      {/* Experiments Tab Content */}
      {activeTab === "experiments" && <PerformanceExperiments disabled={!canMutate} />}

      {/* Admin User Management Tab */}
      {activeTab === "users" && isAdmin && (
        <UserManagement currentUser={currentUser} />
      )}

      {/* Admin Audit Log Viewer Tab */}
      {activeTab === "audit" && isAdmin && (
        <AuditLogViewer />
      )}

      {/* Login / Switch Account Modal */}
      <LoginModal
        isOpen={isLoginModalOpen}
        onClose={() => setIsLoginModalOpen(false)}
        onLoginSuccess={(user) => {
          setCurrentUser(user);
          refreshAll();
        }}
      />
    </div>
  );
}

function StatCard({ label, value, hint }) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-4">
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p className="text-2xl font-semibold mt-1">{value}</p>
      {hint && <p className="text-xs text-slate-400 mt-1">{hint}</p>}
    </div>
  );
}
