import { useState } from "react";
import { deleteDeployment, stopDeployment } from "../api/client";

function formatDate(isoString) {
  return new Date(isoString).toLocaleString();
}

const STATUS_STYLES = {
  running: "bg-emerald-100 text-emerald-700",
  deploying: "bg-amber-100 text-amber-700",
  stopped: "bg-slate-100 text-slate-600",
  failed: "bg-red-100 text-red-700",
};

export default function DeploymentList({ deployments, loading, error, onChanged }) {
  const [busyId, setBusyId] = useState(null);

  async function handleStop(id) {
    setBusyId(id);
    try {
      await stopDeployment(id);
      onChanged?.();
    } finally {
      setBusyId(null);
    }
  }

  async function handleDelete(id) {
    if (!confirm("Remove this deployment record?")) return;
    setBusyId(id);
    try {
      await deleteDeployment(id);
      onChanged?.();
    } finally {
      setBusyId(null);
    }
  }

  if (loading) {
    return <p className="text-sm text-slate-500">Loading deployments...</p>;
  }

  if (error) {
    return (
      <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">
        Failed to load deployments: {error}
      </p>
    );
  }

  if (deployments.length === 0) {
    return (
      <p className="text-sm text-slate-500">
        No deployments yet. Deploy a model version to see it here.
      </p>
    );
  }

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs uppercase tracking-wide text-slate-500 bg-slate-50">
            <th className="px-5 py-2">Model</th>
            <th className="px-5 py-2">Version</th>
            <th className="px-5 py-2">Runtime</th>
            <th className="px-5 py-2">Status</th>
            <th className="px-5 py-2">Endpoint</th>
            <th className="px-5 py-2">Replicas</th>
            <th className="px-5 py-2">Created</th>
            <th className="px-5 py-2">Actions</th>
          </tr>
        </thead>
        <tbody>
          {deployments.map((d) => (
            <tr key={d.id} className="border-t border-slate-100">
              <td className="px-5 py-2 font-medium">{d.model_name}</td>
              <td className="px-5 py-2">{d.version_label}</td>
              <td className="px-5 py-2">
                {d.is_containerized ? (
                  <span className="inline-flex items-center gap-1 bg-blue-50 text-blue-700 border border-blue-200 px-2 py-0.5 rounded-full text-xs font-semibold">
                    <span className="h-1.5 w-1.5 rounded-full bg-blue-600"></span>
                    Docker
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 bg-slate-100 text-slate-600 px-2 py-0.5 rounded-full text-xs font-medium">
                    Local Process
                  </span>
                )}
              </td>
              <td className="px-5 py-2">
                <span
                  className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
                    STATUS_STYLES[d.status] ?? "bg-slate-100 text-slate-600"
                  }`}
                  title={d.error_message ?? undefined}
                >
                  {d.status}
                </span>
              </td>
              <td className="px-5 py-2 font-mono text-xs text-slate-600">
                {d.endpoint ?? "—"}
              </td>
              <td className="px-5 py-2">
                <span className="font-semibold text-slate-700">{d.active_replicas}</span>
                <span className="text-slate-400">/{d.replicas}</span>
              </td>
              <td className="px-5 py-2 text-slate-500">{formatDate(d.created_at)}</td>
              <td className="px-5 py-2">
                <div className="flex items-center gap-3">
                  {d.status === "running" && (
                    <button
                      onClick={() => handleStop(d.id)}
                      disabled={busyId === d.id}
                      className="text-xs font-medium text-amber-700 hover:text-amber-900 disabled:opacity-50"
                    >
                      Stop
                    </button>
                  )}
                  <button
                    onClick={() => handleDelete(d.id)}
                    disabled={busyId === d.id}
                    className="text-xs font-medium text-red-600 hover:text-red-800 disabled:opacity-50"
                  >
                    Delete
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
