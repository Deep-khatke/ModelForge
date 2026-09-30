import { useCallback, useEffect, useState } from "react";
import {
  fetchDeployments,
  fetchExperiments,
  getExperimentsExportUrl,
  runExperiment,
} from "../api/client";

export default function PerformanceExperiments() {
  const [deployments, setDeployments] = useState([]);
  const [selectedDeploymentId, setSelectedDeploymentId] = useState("");
  const [requestCount, setRequestCount] = useState(100);
  const [featureInput, setFeatureInput] = useState("[1.0, 2.0, 3.0, 4.0]");

  const [experiments, setExperiments] = useState([]);
  const [loadingExp, setLoadingExp] = useState(true);
  const [running, setRunning] = useState(false);
  const [runMessage, setRunMessage] = useState(null);
  const [error, setError] = useState(null);

  const loadDeploymentsData = useCallback(async () => {
    try {
      const data = await fetchDeployments();
      const runningDeps = data.filter((d) => d.status === "running");
      setDeployments(runningDeps);
      if (runningDeps.length > 0 && !selectedDeploymentId) {
        setSelectedDeploymentId(runningDeps[0].id);
      }
    } catch (err) {
      console.error("Failed to load deployments:", err);
    }
  }, [selectedDeploymentId]);

  const loadExperimentsData = useCallback(async () => {
    try {
      setLoadingExp(true);
      const data = await fetchExperiments();
      setExperiments(data || []);
    } catch (err) {
      setError(err.message || "Failed to load experiments history");
    } finally {
      setLoadingExp(false);
    }
  }, []);

  useEffect(() => {
    loadDeploymentsData();
    loadExperimentsData();
  }, [loadDeploymentsData, loadExperimentsData]);

  const handleRunExperiment = async (e) => {
    e.preventDefault();
    if (!selectedDeploymentId) {
      setError("Please select an active deployment");
      return;
    }

    try {
      setRunning(true);
      setError(null);
      setRunMessage(`Executing ${requestCount} benchmark requests...`);

      let parsedFeatures = null;
      if (featureInput.trim()) {
        parsedFeatures = JSON.parse(featureInput);
      }

      const res = await runExperiment({
        deploymentId: selectedDeploymentId,
        requests: parseInt(requestCount, 10),
        features: parsedFeatures,
      });

      setRunMessage(`Experiment completed successfully! (${res.throughput_rps.toFixed(1)} req/sec)`);
      await loadExperimentsData();
    } catch (err) {
      setError(err.message || "Failed to execute experiment");
    } finally {
      setRunning(false);
    }
  };

  const handleExportCSV = () => {
    const url = getExperimentsExportUrl();
    window.open(url, "_blank");
  };

  return (
    <div className="space-y-6">
      {/* Header Banner */}
      <div className="bg-gradient-to-r from-indigo-900 via-indigo-800 to-slate-900 rounded-xl p-6 text-white shadow-md">
        <div className="flex flex-wrap justify-between items-center gap-4">
          <div>
            <h2 className="text-xl font-bold tracking-tight">Controlled Performance Benchmark Experiments</h2>
            <p className="text-indigo-200 text-xs mt-1 max-w-2xl">
              Conduct empirical scalability benchmarks comparing throughput and latency across 1 vs 2 vs 3+ replicas.
              All experiment results are persisted to database and exportable as research artifacts.
            </p>
          </div>
          <button
            onClick={handleExportCSV}
            className="flex items-center gap-2 px-4 py-2 text-xs font-semibold rounded-lg bg-emerald-500 hover:bg-emerald-600 text-white transition-colors shadow"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            Export Experiments CSV
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-rose-50 border border-rose-200 text-rose-700 px-4 py-3 rounded-xl text-sm">
          {error}
        </div>
      )}

      {runMessage && !error && (
        <div className="bg-indigo-50 border border-indigo-200 text-indigo-800 px-4 py-3 rounded-xl text-sm flex items-center justify-between">
          <span>{runMessage}</span>
        </div>
      )}

      {/* Benchmark Runner Form */}
      <div className="bg-white rounded-xl border border-slate-200 p-6 shadow-sm">
        <h3 className="text-sm font-bold text-slate-800 uppercase tracking-wide mb-4">
          Run Controlled Benchmark Experiment
        </h3>
        <form onSubmit={handleRunExperiment} className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">
                Target Deployment
              </label>
              <select
                value={selectedDeploymentId}
                onChange={(e) => setSelectedDeploymentId(e.target.value)}
                disabled={running || deployments.length === 0}
                className="w-full text-xs border border-slate-300 rounded-lg p-2 bg-white text-slate-800 font-medium focus:ring-2 focus:ring-indigo-500 focus:outline-none"
              >
                {deployments.length === 0 ? (
                  <option value="">No active running deployments</option>
                ) : (
                  deployments.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.model_name} (Replicas: {d.replicas}, ID: {d.id.slice(0, 8)})
                    </option>
                  ))
                )}
              </select>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">
                Total Benchmark Requests
              </label>
              <input
                type="number"
                min="10"
                max="5000"
                value={requestCount}
                onChange={(e) => setRequestCount(e.target.value)}
                disabled={running}
                className="w-full text-xs border border-slate-300 rounded-lg p-2 bg-white text-slate-800 font-mono font-medium focus:ring-2 focus:ring-indigo-500 focus:outline-none"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">
                Feature Array (JSON)
              </label>
              <input
                type="text"
                value={featureInput}
                onChange={(e) => setFeatureInput(e.target.value)}
                disabled={running}
                placeholder="[1.0, 2.0, 3.0, 4.0]"
                className="w-full text-xs border border-slate-300 rounded-lg p-2 bg-white text-slate-800 font-mono focus:ring-2 focus:ring-indigo-500 focus:outline-none"
              />
            </div>
          </div>

          <div className="flex justify-end">
            <button
              type="submit"
              disabled={running || deployments.length === 0}
              className={`px-5 py-2.5 text-xs font-bold rounded-lg text-white transition-all shadow ${
                running || deployments.length === 0
                  ? "bg-slate-400 cursor-not-allowed"
                  : "bg-indigo-600 hover:bg-indigo-700 active:scale-95"
              }`}
            >
              {running ? "Benchmarking Replicas..." : "Execute Benchmark Experiment"}
            </button>
          </div>
        </form>
      </div>

      {/* Experiment Results & Comparison Table */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-200 flex justify-between items-center">
          <div>
            <h3 className="text-sm font-bold text-slate-800 uppercase tracking-wide">
              Persisted Experiment Benchmark Log &amp; Scaling Analysis
            </h3>
            <p className="text-xs text-slate-500 mt-0.5">
              Empirical verification data comparing throughput and latency across replica scale
            </p>
          </div>
          <span className="text-xs font-semibold text-slate-600 bg-slate-100 px-3 py-1 rounded-full">
            {experiments.length} Experiments Logged
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs text-slate-700">
            <thead className="bg-slate-50 text-slate-500 font-semibold uppercase tracking-wider border-b border-slate-200">
              <tr>
                <th className="px-4 py-3">Timestamp</th>
                <th className="px-4 py-3">Model</th>
                <th className="px-4 py-3 text-center">Replicas</th>
                <th className="px-4 py-3 text-right">Requests</th>
                <th className="px-4 py-3 text-right">Success / Fail</th>
                <th className="px-4 py-3 text-right">Avg Latency</th>
                <th className="px-4 py-3 text-right">P95 Latency</th>
                <th className="px-4 py-3 text-right">Throughput</th>
                <th className="px-4 py-3 text-right">Error Rate</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {loadingExp ? (
                <tr>
                  <td colSpan="9" className="px-4 py-8 text-center text-slate-400">
                    Loading benchmark history...
                  </td>
                </tr>
              ) : experiments.length === 0 ? (
                <tr>
                  <td colSpan="9" className="px-4 py-8 text-center text-slate-400">
                    No experiments executed yet. Run a benchmark experiment above to record scalable performance logs.
                  </td>
                </tr>
              ) : (
                experiments.map((exp) => (
                  <tr key={exp.id} className="hover:bg-slate-50 transition-colors">
                    <td className="px-4 py-3 font-mono text-slate-500">
                      {new Date(exp.completed_at).toLocaleString()}
                    </td>
                    <td className="px-4 py-3 font-semibold text-slate-900">{exp.model_name}</td>
                    <td className="px-4 py-3 text-center">
                      <span className={`px-2 py-0.5 rounded-full font-bold text-xs ${
                        exp.replica_count === 1
                          ? "bg-slate-100 text-slate-700"
                          : exp.replica_count === 2
                          ? "bg-indigo-100 text-indigo-700"
                          : "bg-emerald-100 text-emerald-700"
                      }`}>
                        {exp.replica_count} {exp.replica_count === 1 ? "Replica" : "Replicas"}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right font-medium">{exp.total_requests}</td>
                    <td className="px-4 py-3 text-right font-mono">
                      <span className="text-emerald-700 font-semibold">{exp.successful_requests}</span> /{" "}
                      <span className={exp.failed_requests > 0 ? "text-rose-600 font-bold" : "text-slate-400"}>
                        {exp.failed_requests}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right font-mono">{exp.average_latency_ms.toFixed(1)} ms</td>
                    <td className="px-4 py-3 text-right font-mono font-bold text-indigo-900">
                      {exp.p95_latency_ms.toFixed(1)} ms
                    </td>
                    <td className="px-4 py-3 text-right font-mono font-bold text-emerald-700">
                      {exp.throughput_rps.toFixed(1)} req/s
                    </td>
                    <td className="px-4 py-3 text-right font-mono">
                      <span
                        className={`px-1.5 py-0.5 rounded ${
                          exp.error_rate_percent > 5
                            ? "bg-rose-100 text-rose-700 font-bold"
                            : "text-slate-600"
                        }`}
                      >
                        {exp.error_rate_percent.toFixed(1)}%
                      </span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
