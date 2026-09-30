import { useCallback, useEffect, useState } from "react";
import { fetchInferenceLogs, runLoadTest } from "../api/client";

export default function LoadBalancingSection({ deployment, onInferenceRan }) {
  const [logs, setLogs] = useState([]);
  const [logsLoading, setLogsLoading] = useState(false);
  const [testRequests, setTestRequests] = useState(15);
  const [testLoading, setTestLoading] = useState(false);
  const [testResult, setTestResult] = useState(null);
  const [testError, setTestError] = useState(null);

  const loadLogs = useCallback(async () => {
    if (!deployment?.id) return;
    setLogsLoading(true);
    try {
      const data = await fetchInferenceLogs(deployment.id);
      setLogs(data);
    } catch {
      // ignore log fetch failure
    } finally {
      setLogsLoading(false);
    }
  }, [deployment?.id]);

  useEffect(() => {
    loadLogs();
  }, [loadLogs]);

  async function handleRunLoadTest(e) {
    e.preventDefault();
    if (!deployment?.id) return;

    setTestLoading(true);
    setTestError(null);
    setTestResult(null);

    try {
      const res = await runLoadTest(deployment.id, testRequests);
      setTestResult(res);
      await loadLogs();
      onInferenceRan?.();
    } catch (err) {
      setTestError(err.message);
    } finally {
      setTestLoading(false);
    }
  }

  if (!deployment) return null;

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-6 space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-100 pb-3">
        <div>
          <h3 className="text-lg font-bold text-slate-800">
            Round-Robin Load Balancing &amp; Benchmark
          </h3>
          <p className="text-xs text-slate-500">
            Demonstrating active traffic distribution across {deployment.active_replicas} inference replica(s)
          </p>
        </div>

        {/* Load Test Trigger Form */}
        <form onSubmit={handleRunLoadTest} className="flex items-center gap-2">
          <label className="text-xs font-semibold text-slate-600">Requests:</label>
          <input
            type="number"
            min="1"
            max="100"
            value={testRequests}
            onChange={(e) => setTestRequests(Number(e.target.value))}
            className="w-16 text-sm font-mono border border-slate-300 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
          <button
            type="submit"
            disabled={testLoading || deployment.status !== "running"}
            className="bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-semibold px-4 py-2 rounded-lg disabled:opacity-50 transition-colors flex items-center gap-1.5"
          >
            {testLoading ? (
              <>
                <svg className="animate-spin h-3.5 w-3.5 text-white" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                </svg>
                Testing...
              </>
            ) : (
              "Run Load Test"
            )}
          </button>
        </form>
      </div>

      {testError && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-xs rounded-lg p-3">
          {testError}
        </div>
      )}

      {/* Benchmark Results Display */}
      {testResult && (
        <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 space-y-4">
          <h4 className="text-xs font-bold uppercase tracking-wider text-slate-700">
            Load Test Benchmark Summary
          </h4>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-center">
            <div className="bg-white border border-slate-200 p-2.5 rounded-lg">
              <p className="text-[11px] uppercase tracking-wide text-slate-500 font-medium">Total Requests</p>
              <p className="text-lg font-bold text-slate-800 mt-0.5">{testResult.total_requests}</p>
            </div>
            <div className="bg-white border border-slate-200 p-2.5 rounded-lg">
              <p className="text-[11px] uppercase tracking-wide text-slate-500 font-medium">Successful</p>
              <p className="text-lg font-bold text-emerald-600 mt-0.5">{testResult.successful_requests}</p>
            </div>
            <div className="bg-white border border-slate-200 p-2.5 rounded-lg">
              <p className="text-[11px] uppercase tracking-wide text-slate-500 font-medium">Avg Latency</p>
              <p className="text-lg font-bold text-indigo-600 mt-0.5">{testResult.average_latency_ms} ms</p>
            </div>
            <div className="bg-white border border-slate-200 p-2.5 rounded-lg">
              <p className="text-[11px] uppercase tracking-wide text-slate-500 font-medium">Throughput</p>
              <p className="text-lg font-bold text-slate-800 mt-0.5">{testResult.throughput_requests_per_second} req/s</p>
            </div>
          </div>

          {/* Replica Traffic Distribution Breakdown */}
          <div>
            <p className="text-xs font-semibold text-slate-700 mb-2">
              Replica Traffic Distribution (Round-Robin):
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-3 md:grid-cols-5 gap-2">
              {Object.entries(testResult.replica_distribution || {}).map(([repId, count]) => {
                const percentage = Math.round((count / testResult.total_requests) * 100);
                return (
                  <div key={repId} className="bg-white border border-indigo-100 rounded-lg p-3 text-center shadow-2xs">
                    <span className="font-mono text-xs font-bold text-indigo-900 block">{repId}</span>
                    <span className="text-base font-bold text-slate-800 block mt-1">{count} reqs</span>
                    <span className="text-[10px] text-slate-400 block font-medium">{percentage}% share</span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* Recent Inference Requests Table */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-600">
            Recent Request Log Trace (Load Balancer Output)
          </h4>
          <button
            onClick={loadLogs}
            disabled={logsLoading}
            className="text-xs font-medium text-indigo-600 hover:text-indigo-800 disabled:opacity-50"
          >
            {logsLoading ? "Refreshing..." : "Refresh Logs"}
          </button>
        </div>

        {logs.length === 0 ? (
          <p className="text-xs text-slate-400">No inference logs recorded yet for this deployment.</p>
        ) : (
          <div className="overflow-x-auto border border-slate-200 rounded-lg max-h-60 overflow-y-auto">
            <table className="w-full text-xs text-left">
              <thead className="bg-slate-100 text-slate-600 uppercase tracking-wider sticky top-0">
                <tr>
                  <th className="px-4 py-2">Timestamp</th>
                  <th className="px-4 py-2">Routed Replica</th>
                  <th className="px-4 py-2">Version</th>
                  <th className="px-4 py-2">Latency</th>
                  <th className="px-4 py-2">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 bg-white font-mono">
                {logs.map((log) => (
                  <tr key={log.id}>
                    <td className="px-4 py-2 text-slate-500 font-sans">
                      {new Date(log.timestamp).toLocaleTimeString()}
                    </td>
                    <td className="px-4 py-2 font-bold text-indigo-700">{log.replica_id}</td>
                    <td className="px-4 py-2 text-slate-700">{log.model_version}</td>
                    <td className="px-4 py-2 text-slate-700">{log.latency_ms} ms</td>
                    <td className="px-4 py-2 font-sans">
                      <span
                        className={`inline-block px-2 py-0.5 rounded text-[10px] font-semibold ${
                          log.status === "success"
                            ? "bg-emerald-100 text-emerald-800"
                            : "bg-red-100 text-red-800"
                        }`}
                      >
                        {log.status}
                      </span>
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
