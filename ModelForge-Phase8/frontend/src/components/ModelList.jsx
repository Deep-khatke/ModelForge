import { useState } from "react";
import { activateVersion, createDeployment, deleteModel } from "../api/client";

function formatBytes(bytes) {
  if (!bytes) return "0 KB";
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  return `${(kb / 1024).toFixed(2)} MB`;
}

function formatDate(isoString) {
  return new Date(isoString).toLocaleString();
}

export default function ModelList({ models, loading, error, onChanged }) {
  const [busyKey, setBusyKey] = useState(null);

  async function handleActivate(modelId, version) {
    setBusyKey(`${modelId}-${version}`);
    try {
      await activateVersion(modelId, version);
      onChanged?.();
    } finally {
      setBusyKey(null);
    }
  }

  async function handleDelete(modelId) {
    if (!confirm("Delete this model and all of its versions?")) return;
    setBusyKey(modelId);
    try {
      await deleteModel(modelId);
      onChanged?.();
    } finally {
      setBusyKey(null);
    }
  }

  async function handleDeploy(modelId, version) {
    const key = `deploy-${modelId}-${version}`;
    setBusyKey(key);
    try {
      const deployment = await createDeployment({ modelId, version });
      if (deployment.status === "failed") {
        alert(`Deployment failed: ${deployment.error_message}`);
      }
      onChanged?.();
    } catch (err) {
      alert(`Deployment failed: ${err.message}`);
    } finally {
      setBusyKey(null);
    }
  }

  if (loading) {
    return <p className="text-sm text-slate-500">Loading models...</p>;
  }

  if (error) {
    return (
      <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">
        Failed to load models: {error}
      </p>
    );
  }

  if (models.length === 0) {
    return (
      <p className="text-sm text-slate-500">
        No models registered yet. Upload one to get started.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      {models.map((model) => (
        <div
          key={model.id}
          className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden"
        >
          <div className="flex items-center justify-between px-5 py-3 border-b border-slate-100 bg-slate-50">
            <div>
              <h3 className="font-semibold">{model.name}</h3>
              <p className="text-xs text-slate-500">
                {model.versions.length} version
                {model.versions.length === 1 ? "" : "s"}
              </p>
            </div>
            <button
              onClick={() => handleDelete(model.id)}
              disabled={busyKey === model.id}
              className="text-xs font-medium text-red-600 hover:text-red-800 disabled:opacity-50"
            >
              Delete model
            </button>
          </div>

          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-5 py-2">Version</th>
                <th className="px-5 py-2">Framework</th>
                <th className="px-5 py-2">Type</th>
                <th className="px-5 py-2">Size</th>
                <th className="px-5 py-2">Status</th>
                <th className="px-5 py-2">Uploaded</th>
                <th className="px-5 py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {model.versions.map((v) => {
                const key = `${model.id}-${v.version}`;
                return (
                  <tr key={v.id} className="border-t border-slate-100">
                    <td className="px-5 py-2 font-medium">{v.version}</td>
                    <td className="px-5 py-2">{v.framework}</td>
                    <td className="px-5 py-2">{v.model_type ?? "—"}</td>
                    <td className="px-5 py-2">{formatBytes(v.file_size_bytes)}</td>
                    <td className="px-5 py-2">
                      {v.is_active ? (
                        <span className="inline-block rounded-full bg-emerald-100 text-emerald-700 px-2 py-0.5 text-xs font-medium">
                          active
                        </span>
                      ) : (
                        <span className="inline-block rounded-full bg-slate-100 text-slate-600 px-2 py-0.5 text-xs font-medium">
                          {v.status}
                        </span>
                      )}
                    </td>
                    <td className="px-5 py-2 text-slate-500">
                      {formatDate(v.created_at)}
                    </td>
                    <td className="px-5 py-2">
                      <div className="flex items-center gap-3">
                        {!v.is_active && (
                          <button
                            onClick={() => handleActivate(model.id, v.version)}
                            disabled={busyKey === key}
                            className="text-xs font-medium text-indigo-600 hover:text-indigo-800 disabled:opacity-50"
                          >
                            Activate
                          </button>
                        )}
                        <button
                          onClick={() => handleDeploy(model.id, v.version)}
                          disabled={busyKey === `deploy-${model.id}-${v.version}`}
                          className="text-xs font-medium text-emerald-700 hover:text-emerald-900 disabled:opacity-50"
                        >
                          Deploy
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}
