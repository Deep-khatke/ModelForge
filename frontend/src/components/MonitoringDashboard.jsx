import { useCallback, useEffect, useState } from "react";
import { fetchMonitoringAlerts, fetchMonitoringDeployments, fetchMonitoringReplicas, fetchMonitoringSummary, fetchMonitoringTimeseries, fetchRecentInferences, fetchSystemMetrics, getMonitoringExportUrl } from "../api/client";

const RANGES = ["5m", "15m", "1h", "6h", "24h", "all"];
const format = (value, digits = 1) => Number(value || 0).toFixed(digits);

export default function MonitoringDashboard() {
  const [range, setRange] = useState("1h");
  const [deploymentId, setDeploymentId] = useState("");
  const [live, setLive] = useState(true);
  const [data, setData] = useState({ summary: null, deployments: [], series: [], replicas: [], recent: [], system: null, alerts: [] });
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setError("");
      const [summary, deployments, series, system, alerts, recent] = await Promise.all([
        fetchMonitoringSummary(range), fetchMonitoringDeployments(range), fetchMonitoringTimeseries(range, deploymentId || null),
        fetchSystemMetrics(), fetchMonitoringAlerts(range), fetchRecentInferences(range, deploymentId || null),
      ]);
      const replicas = deploymentId ? await fetchMonitoringReplicas(deploymentId, range) : [];
      setData({ summary, deployments, series, system, alerts, recent: recent.items || [], replicas });
    } catch (err) { setError(err.message || "Unable to load monitoring data."); }
  }, [range, deploymentId]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!live) return undefined;
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  }, [live, load]);

  const summary = data.summary;
  const selected = data.deployments.find((item) => item.deployment_id === deploymentId);
  return <div className="space-y-6">
    <div className="bg-white border border-slate-200 rounded-xl p-4 flex flex-wrap gap-3 items-center justify-between shadow-sm">
      <div className="flex gap-1 rounded-lg bg-slate-100 p-1">{RANGES.map((item) => <button key={item} onClick={() => setRange(item)} className={`px-3 py-1.5 rounded text-xs font-semibold ${range === item ? "bg-indigo-600 text-white" : "text-slate-600"}`}>{item === "all" ? "All time" : `Last ${item}`}</button>)}</div>
      <div className="flex flex-wrap gap-2 items-center">
        <select value={deploymentId} onChange={(event) => setDeploymentId(event.target.value)} className="border rounded-lg p-2 text-xs"><option value="">All deployments</option>{data.deployments.map((item) => <option key={item.deployment_id} value={item.deployment_id}>{item.model_name} {item.version_label} · {item.deployment_id.slice(0, 8)}</option>)}</select>
        <button onClick={() => setLive(!live)} className={`rounded-lg px-3 py-2 text-xs font-semibold ${live ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-600"}`}>{live ? "Live · 5s" : "Refresh paused"}</button>
        <button onClick={load} className="border rounded-lg px-3 py-2 text-xs font-semibold">Refresh</button>
        <a href={getMonitoringExportUrl(range, deploymentId || null)} className="bg-indigo-600 text-white rounded-lg px-3 py-2 text-xs font-semibold">Export CSV</a>
      </div>
    </div>
    {error && <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>}
    {data.alerts.map((alert, index) => <div key={`${alert.title}-${index}`} className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">⚠ <strong>{alert.title}</strong> — {alert.message}</div>)}
    <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-3">
      <Card label="Total Requests" value={summary?.total_requests ?? "—"} /><Card label="Successful" value={summary?.successful_requests ?? "—"} /><Card label="Failed" value={summary?.failed_requests ?? "—"} /><Card label="Average Latency" value={summary ? `${format(summary.average_latency_ms)} ms` : "—"} /><Card label="P95 Latency" value={summary ? `${format(summary.p95_latency_ms)} ms` : "—"} /><Card label="Throughput" value={summary ? `${format(summary.throughput_rps, 2)} req/s` : "—"} /><Card label="Error Rate" value={summary ? `${format(summary.error_rate_percent)}%` : "—"} /><Card label="Active Replicas" value={summary?.active_replicas_count ?? "—"} />
    </div>
    <div className="grid lg:grid-cols-3 gap-6"><Panel title="Requests Over Time"><Bars data={data.series} field="request_count" suffix=" requests" /></Panel><Panel title="Inference Latency Over Time"><Bars data={data.series} field="average_latency_ms" suffix=" ms" color="bg-rose-500" /></Panel><Panel title="Error Rate Over Time"><Bars data={data.series} field="error_rate_percent" suffix="%" color="bg-amber-500" /></Panel></div>
    <div className="grid lg:grid-cols-3 gap-6"><Panel title="Replica Request Distribution" className="lg:col-span-2"><ReplicaDistribution replicas={data.replicas} /></Panel><Panel title="Local/Host Resource Metrics"><p className="text-xs text-slate-500 mb-3">These values describe the local host, not cloud infrastructure.</p><p className="text-sm">CPU utilization <strong className="float-right">{data.system?.cpu_percent == null ? "N/A" : `${format(data.system.cpu_percent)}%`}</strong></p><p className="text-sm mt-3">Memory utilization <strong className="float-right">{data.system?.memory_percent == null ? "N/A" : `${format(data.system.memory_percent)}%`}</strong></p>{selected && <p className="text-xs mt-5 text-slate-600"><strong>{selected.status.toUpperCase()}</strong><br />{selected.active_replicas} / {selected.replicas} replicas healthy</p>}</Panel></div>
    <Panel title="Deployment Monitoring"><Table headers={["Deployment", "Model / Version", "Replicas", "Requests", "Avg latency", "P95", "Throughput", "Error rate", "Health"]}>{data.deployments.map((item) => <tr key={item.deployment_id}><Cell>{item.deployment_id.slice(0, 8)}</Cell><Cell>{item.model_name} {item.version_label}</Cell><Cell>{item.active_replicas}/{item.replicas}</Cell><Cell>{item.total_requests}</Cell><Cell>{format(item.average_latency_ms)} ms</Cell><Cell>{format(item.p95_latency_ms)} ms</Cell><Cell>{format(item.throughput_rps, 2)} req/s</Cell><Cell>{format(item.error_rate_percent)}%</Cell><Cell>{item.status === "running" && item.active_replicas === item.replicas ? "RUNNING" : item.status.toUpperCase()}</Cell></tr>)}</Table></Panel>
    <Panel title="Recent Inference Requests"><Table headers={["Time", "Model version", "Replica", "Latency", "Status"]}>{data.recent.map((item) => <tr key={item.id}><Cell>{new Date(item.timestamp).toLocaleString()}</Cell><Cell>{item.model_version}</Cell><Cell>{item.replica_id}</Cell><Cell>{format(item.latency_ms, 3)} ms</Cell><Cell>{item.status.toUpperCase()}</Cell></tr>)}</Table></Panel>
  </div>;
}

function Card({ label, value }) { return <div className="bg-white rounded-xl border border-slate-200 p-3 shadow-sm"><p className="text-[10px] uppercase font-bold tracking-wide text-slate-500">{label}</p><p className="text-xl mt-1 font-bold text-slate-900">{value}</p></div>; }
function Panel({ title, children, className = "" }) { return <section className={`bg-white rounded-xl border border-slate-200 shadow-sm p-5 ${className}`}><h3 className="text-sm font-bold uppercase tracking-wide text-slate-800 mb-4">{title}</h3>{children}</section>; }
function Cell({ children }) { return <td className="px-3 py-2 border-t border-slate-100 whitespace-nowrap">{children}</td>; }
function Table({ headers, children }) { return <div className="overflow-auto"><table className="w-full text-left text-xs text-slate-700"><thead className="text-slate-500"><tr>{headers.map((header) => <th key={header} className="px-3 py-2 whitespace-nowrap">{header}</th>)}</tr></thead><tbody>{children}</tbody></table></div>; }
function Bars({ data, field, suffix, color = "bg-indigo-600" }) { if (!data.length) return <p className="h-32 grid place-items-center text-xs text-slate-400">No measurements in this range.</p>; const maximum = Math.max(...data.map((point) => point[field] || 0), 1); return <div className="h-32 flex gap-1 items-end">{data.map((point, index) => <div className="flex-1 group relative" key={index} title={`${new Date(point.timestamp).toLocaleTimeString()}: ${format(point[field])}${suffix}`}><div className={`${color} rounded-t min-h-1`} style={{ height: `${Math.max(2, ((point[field] || 0) / maximum) * 100)}%` }} /></div>)}</div>; }
function ReplicaDistribution({ replicas }) { if (!replicas.length) return <p className="text-xs text-slate-400">Select a deployment to see measured replica traffic.</p>; const max = Math.max(...replicas.map((item) => item.request_count), 1); return <div className="space-y-3">{replicas.map((item) => <div key={item.replica_id}><div className="text-xs flex justify-between"><span>{item.replica_id} · {item.status}</span><strong>{item.request_count} requests</strong></div><div className="h-2 mt-1 bg-slate-100 rounded"><div className="h-2 bg-indigo-600 rounded" style={{ width: `${(item.request_count / max) * 100}%` }} /></div></div>)}</div>; }
