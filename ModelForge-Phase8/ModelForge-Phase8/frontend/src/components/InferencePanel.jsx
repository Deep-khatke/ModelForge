import { useEffect, useState } from "react";
import { predictModel } from "../api/client";

export default function InferencePanel({ models, deployments, onRequestExecuted }) {
  const runningDeployments = deployments.filter((d) => d.status === "running");

  const [selectedModelId, setSelectedModelId] = useState("");
  const [featureInput, setFeatureInput] = useState("0, 0");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);

  // Synchronize selected model when running deployments change
  useEffect(() => {
    if (runningDeployments.length > 0) {
      if (!selectedModelId || !runningDeployments.some((d) => d.model_id === selectedModelId)) {
        setSelectedModelId(runningDeployments[0].model_id);
      }
    } else {
      setSelectedModelId("");
    }
  }, [runningDeployments, selectedModelId]);

  const activeDeployment = runningDeployments.find((d) => d.model_id === selectedModelId);
  const activeModel = models.find((m) => m.id === selectedModelId);

  async function handlePredict(e) {
    e.preventDefault();
    if (!selectedModelId) return;

    setError(null);
    setResult(null);

    let parsedFeatures;
    const trimmed = featureInput.trim();

    try {
      if (trimmed.startsWith("[") || trimmed.startsWith("{")) {
        parsedFeatures = JSON.parse(trimmed);
      } else {
        // Parse comma or space separated numbers
        parsedFeatures = trimmed
          .split(/[\s,]+/)
          .filter((val) => val.length > 0)
          .map((val) => {
            const num = Number(val);
            if (isNaN(num)) {
              throw new Error(`'${val}' is not a valid number`);
            }
            return num;
          });
      }

      if (!Array.isArray(parsedFeatures) || parsedFeatures.length === 0) {
        throw new Error("Input must be a non-empty array or comma-separated numbers");
      }
    } catch (parseErr) {
      setError(`Input format error: ${parseErr.message}`);
      return;
    }

    setLoading(true);
    try {
      const res = await predictModel(selectedModelId, parsedFeatures);
      setResult(res);
      onRequestExecuted?.();
    } catch (err) {
      setError(err.message || "Prediction failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-6">
      <div className="flex items-center justify-between mb-4 border-b border-slate-100 pb-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-800">Inference Test Bench</h2>
          <p className="text-xs text-slate-500">
            Submit real-time feature arrays to running model deployments (Phase 3)
          </p>
        </div>
        {activeDeployment && (
          <span className="bg-emerald-50 text-emerald-700 text-xs font-medium px-2.5 py-1 rounded-full border border-emerald-200 flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
            Serving {activeDeployment.model_name} ({activeDeployment.version_label})
          </span>
        )}
      </div>

      {runningDeployments.length === 0 ? (
        <div className="bg-amber-50 border border-amber-200 text-amber-800 rounded-lg p-4 text-sm">
          <p className="font-medium">No active model deployments available.</p>
          <p className="text-xs mt-1 text-amber-700">
            Deploy a model version from the <strong>Models</strong> table above to start running live predictions.
          </p>
        </div>
      ) : (
        <form onSubmit={handlePredict} className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="md:col-span-1">
              <label className="block text-xs font-semibold uppercase tracking-wider text-slate-600 mb-1">
                Select Model
              </label>
              <select
                value={selectedModelId}
                onChange={(e) => setSelectedModelId(e.target.value)}
                className="w-full text-sm rounded-lg border border-slate-300 px-3 py-2 bg-slate-50 focus:bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
              >
                {runningDeployments.map((d) => (
                  <option key={d.id} value={d.model_id}>
                    {d.model_name} ({d.version_label})
                  </option>
                ))}
              </select>
            </div>

            <div className="md:col-span-2">
              <label className="block text-xs font-semibold uppercase tracking-wider text-slate-600 mb-1">
                Input Features
              </label>
              <input
                type="text"
                value={featureInput}
                onChange={(e) => setFeatureInput(e.target.value)}
                placeholder="e.g. 0.5, 1.2 or [0.5, 1.2]"
                className="w-full text-sm font-mono rounded-lg border border-slate-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
              <p className="text-xs text-slate-400 mt-1">
                Enter numbers separated by commas (e.g. <code className="bg-slate-100 px-1 py-0.5 rounded">0, 0</code>) or JSON array (e.g. <code className="bg-slate-100 px-1 py-0.5 rounded">[[0, 0], [1, 1]]</code>).
              </p>
            </div>
          </div>

          <div className="flex justify-end">
            <button
              type="submit"
              disabled={loading || !selectedModelId}
              className="bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50 text-sm font-medium px-5 py-2 rounded-lg shadow-sm transition-colors flex items-center gap-2"
            >
              {loading ? (
                <>
                  <svg className="animate-spin h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                  </svg>
                  Running Inference...
                </>
              ) : (
                "Run Inference"
              )}
            </button>
          </div>
        </form>
      )}

      {error && (
        <div className="mt-4 bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg p-3">
          <span className="font-semibold">Inference Error:</span> {error}
        </div>
      )}

      {result && (
        <div className="mt-6 bg-slate-50 border border-slate-200 rounded-xl p-4">
          <div className="flex items-center justify-between mb-3 border-b border-slate-200 pb-2">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-600">
              Inference Results
            </h3>
            <div className="flex items-center gap-2">
              {result.replica_id && (
                <span className="bg-indigo-50 text-indigo-700 border border-indigo-200 font-mono text-xs px-2.5 py-0.5 rounded-full font-semibold">
                  Routed: {result.replica_id}
                </span>
              )}
              <span className="bg-slate-200 text-slate-800 font-mono text-xs px-2 py-0.5 rounded-full font-medium">
                Latency: {result.inference_time_ms} ms
              </span>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <p className="text-xs text-slate-500 font-medium uppercase tracking-wide">
                Predictions
              </p>
              <div className="mt-1 flex flex-wrap gap-1.5">
                {Array.isArray(result.predictions) ? (
                  result.predictions.map((val, i) => (
                    <span
                      key={i}
                      className="bg-indigo-100 text-indigo-800 font-mono text-sm font-semibold px-2.5 py-1 rounded-md"
                    >
                      {String(val)}
                    </span>
                  ))
                ) : (
                  <span className="bg-indigo-100 text-indigo-800 font-mono text-sm font-semibold px-2.5 py-1 rounded-md">
                    {String(result.predictions)}
                  </span>
                )}
              </div>
            </div>

            {result.probabilities && (
              <div>
                <p className="text-xs text-slate-500 font-medium uppercase tracking-wide">
                  Probabilities
                </p>
                <div className="mt-1 font-mono text-xs bg-white border border-slate-200 rounded p-2 overflow-x-auto">
                  <pre className="text-slate-700">{JSON.stringify(result.probabilities, null, 2)}</pre>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
