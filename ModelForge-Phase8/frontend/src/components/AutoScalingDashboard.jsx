import { useCallback, useEffect, useState } from "react";
import {
  evaluateAutoScaling,
  fetchAutoScalingConfig,
  fetchDeployments,
  fetchScalingEvents,
  updateAutoScalingConfig,
} from "../api/client";

function formatDate(isoString) {
  if (!isoString) return "Never";
  return new Date(isoString).toLocaleString();
}

const ACTION_BADGES = {
  SCALE_UP: "bg-emerald-100 text-emerald-800 border-emerald-200",
  SCALE_DOWN: "bg-blue-100 text-blue-800 border-blue-200",
  NO_ACTION: "bg-slate-100 text-slate-700 border-slate-200",
};

export default function AutoScalingDashboard() {
  const [deployments, setDeployments] = useState([]);
  const [selectedDepId, setSelectedDepId] = useState("");
  const [loading, setLoading] = useState(false);
  const [configLoading, setConfigLoading] = useState(false);
  const [eventsLoading, setEventsLoading] = useState(false);
  const [evaluating, setEvaluating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [successNotice, setSuccessNotice] = useState(null);

  // Config Form State
  const [config, setConfig] = useState(null);
  const [enabled, setEnabled] = useState(false);
  const [minReplicas, setMinReplicas] = useState(1);
  const [maxReplicas, setMaxReplicas] = useState(5);
  const [targetLatencyMs, setTargetLatencyMs] = useState(200);
  const [targetThroughputRps, setTargetThroughputRps] = useState(50);
  const [scaleUpErrorRate, setScaleUpErrorRate] = useState(10);
  const [scaleDownIdleSec, setScaleDownIdleSec] = useState(120);
  const [cooldownSec, setCooldownSec] = useState(60);
  const [evalIntervalSec, setEvalIntervalSec] = useState(30);

  const [scalingEvents, setScalingEvents] = useState([]);

  // Load Deployments
  const loadDeploymentsList = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchDeployments();
      setDeployments(data);
      if (data.length > 0 && !selectedDepId) {
        // Default to first running deployment or first deployment
        const running = data.find((d) => d.status === "running");
        setSelectedDepId(running ? running.id : data[0].id);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [selectedDepId]);

  useEffect(() => {
    loadDeploymentsList();
  }, [loadDeploymentsList]);

  // Load AutoScaling Config & Scaling Events for selected deployment
  const loadDeploymentData = useCallback(async (depId) => {
    if (!depId) return;
    setConfigLoading(true);
    setEventsLoading(true);
    setError(null);
    try {
      const [cfg, events] = await Promise.all([
        fetchAutoScalingConfig(depId),
        fetchScalingEvents(depId),
      ]);
      setConfig(cfg);
      setEnabled(cfg.enabled);
      setMinReplicas(cfg.min_replicas);
      setMaxReplicas(cfg.max_replicas);
      setTargetLatencyMs(cfg.target_latency_ms);
      setTargetThroughputRps(cfg.target_throughput_rps);
      setScaleUpErrorRate(cfg.scale_up_error_rate_percent);
      setScaleDownIdleSec(cfg.scale_down_idle_seconds);
      setCooldownSec(cfg.cooldown_seconds);
      setEvalIntervalSec(cfg.evaluation_interval_seconds);
      setScalingEvents(events);
    } catch (err) {
      setError(err.message);
    } finally {
      setConfigLoading(false);
      setEventsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (selectedDepId) {
      loadDeploymentData(selectedDepId);
    }
  }, [selectedDepId, loadDeploymentData]);

  // Handle Save Configuration
  async function handleSaveConfig(e) {
    e.preventDefault();
    if (!selectedDepId) return;
    setSaving(true);
    setError(null);
    setSuccessNotice(null);
    try {
      const updated = await updateAutoScalingConfig(selectedDepId, {
        enabled,
        min_replicas: Number(minReplicas),
        max_replicas: Number(maxReplicas),
        target_latency_ms: Number(targetLatencyMs),
        target_throughput_rps: Number(targetThroughputRps),
        scale_up_error_rate_percent: Number(scaleUpErrorRate),
        scale_down_idle_seconds: Number(scaleDownIdleSec),
        cooldown_seconds: Number(cooldownSec),
        evaluation_interval_seconds: Number(evalIntervalSec),
      });
      setConfig(updated);
      setSuccessNotice("Auto-scaling configuration saved successfully.");
      await loadDeploymentsList();
      await loadDeploymentData(selectedDepId);
      setTimeout(() => setSuccessNotice(null), 4000);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  // Handle Evaluate Now
  async function handleEvaluateNow() {
    if (!selectedDepId) return;
    setEvaluating(true);
    setError(null);
    try {
      const res = await evaluateAutoScaling(selectedDepId);
      setSuccessNotice(`Evaluation completed: ${res.action} (${res.trigger_reason})`);
      await loadDeploymentsList();
      await loadDeploymentData(selectedDepId);
      setTimeout(() => setSuccessNotice(null), 5000);
    } catch (err) {
      setError(err.message);
    } finally {
      setEvaluating(false);
    }
  }

  const selectedDeployment = deployments.find((d) => d.id === selectedDepId);
  const lastEvent = scalingEvents.length > 0 ? scalingEvents[0] : null;

  return (
    <div className="space-y-8">
      {/* Top Banner & Deployment Selector */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-6 flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-slate-800 flex items-center gap-2">
            Intelligent Auto-Scaling
            <span className="text-xs bg-indigo-100 text-indigo-800 font-semibold px-2.5 py-0.5 rounded-full uppercase">
              Phase 7
            </span>
          </h2>
          <p className="text-sm text-slate-500 mt-0.5">
            Telemetry-driven autonomous scaling based on real P95 latency, throughput capacity, error rates, and idle detection.
          </p>
        </div>

        {/* Deployment Dropdown */}
        <div className="flex items-center gap-3">
          <label htmlFor="dep-select" className="text-xs font-semibold uppercase text-slate-500">
            Target Deployment:
          </label>
          <select
            id="dep-select"
            value={selectedDepId}
            onChange={(e) => setSelectedDepId(e.target.value)}
            disabled={loading || deployments.length === 0}
            className="border border-slate-300 rounded-lg px-3 py-1.5 text-sm bg-white font-medium text-slate-800 shadow-xs focus:ring-2 focus:ring-indigo-500 focus:outline-none"
          >
            {deployments.map((d) => (
              <option key={d.id} value={d.id}>
                {d.model_name} ({d.version_label}) — {d.status.toUpperCase()} [{d.active_replicas}/{d.replicas} reps]
              </option>
            ))}
          </select>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg p-4">
          {error}
        </div>
      )}

      {successNotice && (
        <div className="bg-emerald-50 border border-emerald-200 text-emerald-800 text-sm rounded-lg p-4 flex items-center justify-between animate-fade-in">
          <span>{successNotice}</span>
          <button
            onClick={() => setSuccessNotice(null)}
            className="text-emerald-700 hover:text-emerald-900 font-bold ml-4"
          >
            ✕
          </button>
        </div>
      )}

      {/* Live Readout Status Cards */}
      {selectedDeployment && config && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm">
            <p className="text-xs uppercase tracking-wide text-slate-500 font-semibold">Auto-Scaling Mode</p>
            <div className="mt-2 flex items-center gap-2">
              <span
                className={`h-2.5 w-2.5 rounded-full ${
                  config.enabled ? "bg-emerald-500 animate-pulse" : "bg-slate-400"
                }`}
              ></span>
              <span className="text-base font-bold text-slate-800">
                {config.enabled ? "ACTIVE (Autonomous)" : "DISABLED (Manual Only)"}
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-1">
              Bounds: {config.min_replicas} – {config.max_replicas} replicas
            </p>
          </div>

          <div className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm">
            <p className="text-xs uppercase tracking-wide text-slate-500 font-semibold">Current Replicas</p>
            <p className="text-2xl font-extrabold text-indigo-700 mt-1">
              {selectedDeployment.active_replicas}
              <span className="text-sm font-normal text-slate-400 ml-1">
                / {selectedDeployment.replicas} requested
              </span>
            </p>
            <p className="text-xs text-slate-400 mt-1">
              Runtime: {selectedDeployment.is_containerized ? "Docker Containers" : "Local Process"}
            </p>
          </div>

          <div className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm">
            <p className="text-xs uppercase tracking-wide text-slate-500 font-semibold">Cooldown Status</p>
            <div className="mt-2">
              {config.is_in_cooldown ? (
                <span className="bg-amber-100 text-amber-800 border border-amber-200 text-xs font-semibold px-2 py-0.5 rounded-md">
                  Active ({config.cooldown_remaining_seconds}s remaining)
                </span>
              ) : (
                <span className="bg-emerald-100 text-emerald-800 border border-emerald-200 text-xs font-semibold px-2 py-0.5 rounded-md">
                  Ready (No Cooldown)
                </span>
              )}
            </div>
            <p className="text-xs text-slate-400 mt-1">
              Last Scaled: {formatDate(config.last_scaled_at)}
            </p>
          </div>

          <div className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm">
            <p className="text-xs uppercase tracking-wide text-slate-500 font-semibold">Last Evaluation</p>
            <p className="text-sm font-semibold text-slate-800 mt-1 truncate" title={lastEvent?.trigger_reason || "None"}>
              {lastEvent ? `${lastEvent.action}` : "None recorded"}
            </p>
            <p className="text-xs text-slate-400 mt-1">
              {formatDate(config.last_evaluated_at)}
            </p>
          </div>
        </div>
      )}

      {/* Auto-Scaling Configuration Form */}
      {selectedDeployment && (
        <form
          onSubmit={handleSaveConfig}
          className="bg-white rounded-xl border border-slate-200 shadow-sm p-6 space-y-6"
        >
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-100 pb-4">
            <div>
              <h3 className="text-base font-bold text-slate-800">
                Scaling Policy &amp; Threshold Configuration
              </h3>
              <p className="text-xs text-slate-500">
                Configure when ModelForge should scale container replicas up or down.
              </p>
            </div>

            <div className="flex items-center gap-3">
              <label className="flex items-center gap-2 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={enabled}
                  onChange={(e) => setEnabled(e.target.checked)}
                  className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                />
                <span className="text-sm font-bold text-slate-800">Enable Auto-Scaling</span>
              </label>

              <button
                type="button"
                onClick={handleEvaluateNow}
                disabled={evaluating || selectedDeployment.status !== "running"}
                className="text-xs font-semibold bg-slate-100 hover:bg-slate-200 text-slate-700 px-3 py-1.5 rounded-lg border border-slate-300 disabled:opacity-50"
              >
                {evaluating ? "Evaluating..." : "Run Evaluation Now"}
              </button>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 text-sm">
            {/* Minimum Replicas */}
            <div>
              <label className="block text-xs font-bold text-slate-700 uppercase tracking-wide mb-1">
                Min Replicas
              </label>
              <input
                type="number"
                min="1"
                max={maxReplicas}
                value={minReplicas}
                onChange={(e) => setMinReplicas(e.target.value)}
                className="w-full border border-slate-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-indigo-500"
                required
              />
              <p className="text-[11px] text-slate-400 mt-1">Lowest replica floor during idle periods.</p>
            </div>

            {/* Maximum Replicas */}
            <div>
              <label className="block text-xs font-bold text-slate-700 uppercase tracking-wide mb-1">
                Max Replicas
              </label>
              <input
                type="number"
                min={minReplicas}
                max="5"
                value={maxReplicas}
                onChange={(e) => setMaxReplicas(e.target.value)}
                className="w-full border border-slate-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-indigo-500"
                required
              />
              <p className="text-[11px] text-slate-400 mt-1">Ceiling cap to prevent resource overconsumption.</p>
            </div>

            {/* Target Latency */}
            <div>
              <label className="block text-xs font-bold text-slate-700 uppercase tracking-wide mb-1">
                P95 Latency Target (ms)
              </label>
              <input
                type="number"
                step="1"
                min="1"
                value={targetLatencyMs}
                onChange={(e) => setTargetLatencyMs(e.target.value)}
                className="w-full border border-slate-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-indigo-500"
                required
              />
              <p className="text-[11px] text-slate-400 mt-1">Scale up if observed P95 latency exceeds this threshold.</p>
            </div>

            {/* Target Throughput */}
            <div>
              <label className="block text-xs font-bold text-slate-700 uppercase tracking-wide mb-1">
                Capacity Target (RPS)
              </label>
              <input
                type="number"
                step="1"
                min="1"
                value={targetThroughputRps}
                onChange={(e) => setTargetThroughputRps(e.target.value)}
                className="w-full border border-slate-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-indigo-500"
                required
              />
              <p className="text-[11px] text-slate-400 mt-1">Scale up when sustained throughput reaches capacity.</p>
            </div>

            {/* Scale-Down Idle Duration */}
            <div>
              <label className="block text-xs font-bold text-slate-700 uppercase tracking-wide mb-1">
                Scale-Down Idle Time (seconds)
              </label>
              <input
                type="number"
                min="10"
                value={scaleDownIdleSec}
                onChange={(e) => setScaleDownIdleSec(e.target.value)}
                className="w-full border border-slate-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-indigo-500"
                required
              />
              <p className="text-[11px] text-slate-400 mt-1">Required idle duration before scaling down towards min replicas.</p>
            </div>

            {/* Cooldown Seconds */}
            <div>
              <label className="block text-xs font-bold text-slate-700 uppercase tracking-wide mb-1">
                Cooldown Period (seconds)
              </label>
              <input
                type="number"
                min="0"
                value={cooldownSec}
                onChange={(e) => setCooldownSec(e.target.value)}
                className="w-full border border-slate-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-indigo-500"
                required
              />
              <p className="text-[11px] text-slate-400 mt-1">Quiet period after scaling to prevent thrashing.</p>
            </div>
          </div>

          <div className="flex justify-end pt-4 border-t border-slate-100">
            <button
              type="submit"
              disabled={saving}
              className="bg-indigo-600 hover:bg-indigo-700 text-white font-bold text-xs px-5 py-2.5 rounded-lg shadow-sm disabled:opacity-50 transition-colors"
            >
              {saving ? "Saving Policy..." : "Save Auto-Scaling Policy"}
            </button>
          </div>
        </form>
      )}

      {/* Scaling Event History Table */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between">
          <div>
            <h3 className="text-base font-bold text-slate-800">
              Scaling Decision History
            </h3>
            <p className="text-xs text-slate-500">
              Complete audit trail of telemetry-based scale decisions, observed metrics, and container outcomes.
            </p>
          </div>
          <button
            onClick={() => loadDeploymentData(selectedDepId)}
            disabled={eventsLoading}
            className="text-xs font-semibold text-indigo-600 hover:text-indigo-800 disabled:opacity-50"
          >
            {eventsLoading ? "Refreshing..." : "Refresh History"}
          </button>
        </div>

        {scalingEvents.length === 0 ? (
          <div className="p-8 text-center text-slate-400 text-sm">
            No scaling decisions recorded yet for this deployment.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-50 text-slate-600 uppercase tracking-wider border-b border-slate-100">
                <tr>
                  <th className="px-5 py-3">Timestamp</th>
                  <th className="px-5 py-3">Action</th>
                  <th className="px-5 py-3">Replicas</th>
                  <th className="px-5 py-3">Trigger Reason</th>
                  <th className="px-5 py-3">P95 Latency</th>
                  <th className="px-5 py-3">Throughput</th>
                  <th className="px-5 py-3">Outcome</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 bg-white">
                {scalingEvents.map((ev) => (
                  <tr key={ev.id} className="hover:bg-slate-50/70 transition-colors">
                    <td className="px-5 py-3 font-mono text-slate-600 whitespace-nowrap">
                      {formatDate(ev.timestamp)}
                    </td>
                    <td className="px-5 py-3">
                      <span
                        className={`inline-block border px-2 py-0.5 rounded-full text-[11px] font-bold ${
                          ACTION_BADGES[ev.action] ?? "bg-slate-100 text-slate-700"
                        }`}
                      >
                        {ev.action}
                      </span>
                    </td>
                    <td className="px-5 py-3 font-mono text-slate-800 whitespace-nowrap">
                      {ev.previous_replicas} → <span className="font-bold">{ev.target_replicas}</span>
                    </td>
                    <td className="px-5 py-3 text-slate-700 max-w-xs md:max-w-sm truncate" title={ev.trigger_reason}>
                      {ev.trigger_reason}
                    </td>
                    <td className="px-5 py-3 font-mono text-slate-700">
                      {ev.observed_p95_latency_ms !== null && ev.observed_p95_latency_ms !== undefined
                        ? `${ev.observed_p95_latency_ms} ms`
                        : "—"}
                    </td>
                    <td className="px-5 py-3 font-mono text-slate-700">
                      {ev.observed_throughput_rps !== null && ev.observed_throughput_rps !== undefined
                        ? `${ev.observed_throughput_rps} RPS`
                        : "—"}
                    </td>
                    <td className="px-5 py-3">
                      {ev.success ? (
                        <span className="text-emerald-700 font-semibold">Success</span>
                      ) : (
                        <span className="text-red-700 font-semibold" title={ev.error_message || "Failed"}>
                          Failed
                        </span>
                      )}
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
