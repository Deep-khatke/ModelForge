import { useCallback, useEffect, useState } from "react";
import { fetchDeploymentReplicas, scaleDeployment } from "../api/client";

export default function ReplicaManagerCard({ deployment, onChanged }) {
  const [replicas, setReplicas] = useState([]);
  const [loading, setLoading] = useState(false);
  const [targetCount, setTargetCount] = useState(deployment?.replicas || 1);
  const [scaling, setScaling] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (deployment?.replicas) {
      setTargetCount(deployment.replicas);
    }
  }, [deployment?.replicas]);

  const loadReplicas = useCallback(async () => {
    if (!deployment?.id) return;
    setLoading(true);
    setError(null);
    try {
      const data = await fetchDeploymentReplicas(deployment.id);
      setReplicas(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [deployment?.id]);

  useEffect(() => {
    loadReplicas();
  }, [loadReplicas]);

  async function handleScale(newCount) {
    if (newCount < 1 || newCount > 5) return;
    setScaling(true);
    setError(null);
    try {
      await scaleDeployment(deployment.id, newCount);
      setTargetCount(newCount);
      await loadReplicas();
      onChanged?.();
    } catch (err) {
      setError(err.message);
    } finally {
      setScaling(false);
    }
  }

  const getStatusBadge = (status, scalingStatus) => {
    if (scaling) {
      return (
        <span className="bg-amber-100 text-amber-800 text-xs font-semibold px-2.5 py-0.5 rounded-full animate-pulse">
          SCALING...
        </span>
      );
    }
    if (scalingStatus === "degraded") {
      return (
        <span className="bg-amber-100 text-amber-700 text-xs font-semibold px-2.5 py-0.5 rounded-full">
          DEGRADED
        </span>
      );
    }
    if (status === "running") {
      return (
        <span className="bg-emerald-100 text-emerald-700 text-xs font-semibold px-2.5 py-0.5 rounded-full">
          RUNNING
        </span>
      );
    }
    return (
      <span className="bg-slate-100 text-slate-700 text-xs font-semibold px-2.5 py-0.5 rounded-full">
        {status.toUpperCase()}
      </span>
    );
  };

  if (!deployment) return null;

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-6 space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-100 pb-4">
        <div>
          <div className="flex items-center gap-3">
            <h3 className="text-lg font-bold text-slate-800">
              {deployment.model_name} <span className="text-slate-400 font-normal">({deployment.version_label})</span>
            </h3>
            {getStatusBadge(deployment.status, deployment.scaling_status)}
            {deployment.is_containerized ? (
              <span className="bg-blue-100 text-blue-800 text-xs font-semibold px-2.5 py-0.5 rounded-full border border-blue-200">
                Docker Containers
              </span>
            ) : (
              <span className="bg-slate-100 text-slate-600 text-xs font-medium px-2.5 py-0.5 rounded-full">
                Local Process
              </span>
            )}
            {deployment.autoscaling_enabled ? (
              <span className="bg-emerald-100 text-emerald-800 text-xs font-semibold px-2.5 py-0.5 rounded-full border border-emerald-200 flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
                Auto-Scaling Active
              </span>
            ) : (
              <span className="bg-slate-100 text-slate-500 text-xs font-medium px-2.5 py-0.5 rounded-full">
                Auto-Scaling Off
              </span>
            )}
          </div>
          <p className="text-xs text-slate-500 mt-1">
            Deployment ID: <code className="font-mono bg-slate-100 px-1 py-0.5 rounded">{deployment.id}</code>
          </p>
        </div>

        {/* Replica Scaler Controls */}
        <div className="flex items-center gap-3 bg-slate-50 border border-slate-200 rounded-lg p-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-600 px-1">
            Replicas
          </span>
          <div className="flex items-center gap-1">
            <button
              onClick={() => handleScale(targetCount - 1)}
              disabled={scaling || targetCount <= 1}
              className="w-8 h-8 rounded-md bg-white border border-slate-300 hover:bg-slate-100 text-slate-700 font-bold text-sm disabled:opacity-40 flex items-center justify-center shadow-xs"
              title="Scale Down"
            >
              −
            </button>
            <span className="w-8 text-center font-mono font-bold text-slate-800 text-base">
              {targetCount}
            </span>
            <button
              onClick={() => handleScale(targetCount + 1)}
              disabled={scaling || targetCount >= 5}
              className="w-8 h-8 rounded-md bg-white border border-slate-300 hover:bg-slate-100 text-slate-700 font-bold text-sm disabled:opacity-40 flex items-center justify-center shadow-xs"
              title="Scale Up"
            >
              +
            </button>
          </div>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-xs rounded-lg p-3">
          {error}
        </div>
      )}

      {/* Scaling Readout */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 bg-slate-50 p-4 rounded-lg border border-slate-200 text-sm">
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-500 font-medium">Requested Replicas</p>
          <p className="text-lg font-bold text-slate-800 mt-0.5">{deployment.replicas}</p>
        </div>
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-500 font-medium">Active Replicas</p>
          <p className="text-lg font-bold text-emerald-600 mt-0.5">
            {deployment.active_replicas} / {deployment.replicas}
          </p>
        </div>
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-500 font-medium">Scaling Status</p>
          <p className="text-lg font-bold text-slate-800 capitalize mt-0.5">
            {scaling ? "Scaling..." : deployment.scaling_status}
          </p>
        </div>
      </div>

      {/* Replicas Detail Table */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-600">
            Active Replica Instances
          </h4>
          <button
            onClick={loadReplicas}
            disabled={loading}
            className="text-xs font-medium text-indigo-600 hover:text-indigo-800 disabled:opacity-50"
          >
            {loading ? "Refreshing..." : "Refresh Status"}
          </button>
        </div>

        {replicas.length === 0 ? (
          <p className="text-xs text-slate-400">No replica instances found.</p>
        ) : (
          <div className="overflow-x-auto border border-slate-200 rounded-lg">
            <table className="w-full text-xs text-left">
              <thead className="bg-slate-100 text-slate-600 uppercase tracking-wider">
                <tr>
                  <th className="px-4 py-2">Replica ID</th>
                  <th className="px-4 py-2">Container / Runtime</th>
                  <th className="px-4 py-2">Status</th>
                  <th className="px-4 py-2">Requests Handled</th>
                  <th className="px-4 py-2">Avg Latency</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 bg-white">
                {replicas.map((r) => (
                  <tr key={r.id}>
                    <td className="px-4 py-2.5 font-mono font-medium text-slate-800">
                      {r.replica_id}
                    </td>
                    <td className="px-4 py-2.5 font-mono text-slate-600">
                      {r.container_id ? (
                        <span className="bg-slate-100 border border-slate-200 px-1.5 py-0.5 rounded text-[11px]" title={`Container: ${r.container_id}`}>
                          {r.container_id.slice(0, 12)}
                        </span>
                      ) : (
                        <span className="text-slate-400 text-[11px] italic">
                          Local Process
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2.5">
                      <span
                        className={`inline-block px-2 py-0.5 rounded-full text-[11px] font-semibold ${
                          r.status === "healthy"
                            ? "bg-emerald-100 text-emerald-700"
                            : "bg-red-100 text-red-700"
                        }`}
                      >
                        {r.status.toUpperCase()}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 font-mono text-slate-700">{r.requests_count}</td>
                    <td className="px-4 py-2.5 font-mono text-slate-700">
                      {r.requests_count > 0 ? `${r.avg_latency_ms} ms` : "N/A"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
