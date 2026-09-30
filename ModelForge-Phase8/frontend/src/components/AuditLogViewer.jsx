import { useState, useEffect } from "react";
import { fetchAuditEvents, getAuditExportUrl } from "../api/client";

export default function AuditLogViewer() {
  const [events, setEvents] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Filter state
  const [actionFilter, setActionFilter] = useState("");
  const [resourceTypeFilter, setResourceTypeFilter] = useState("");
  const [successFilter, setSuccessFilter] = useState("");
  const [page, setPage] = useState(0);
  const limit = 25;

  const [expandedRow, setExpandedRow] = useState(null);

  useEffect(() => {
    loadEvents();
  }, [actionFilter, resourceTypeFilter, successFilter, page]);

  async function loadEvents() {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchAuditEvents({
        action: actionFilter || null,
        resourceType: resourceTypeFilter || null,
        success: successFilter !== "" ? successFilter === "true" : null,
        limit,
        offset: page * limit,
      });
      setEvents(data.items);
      setTotal(data.total);
    } catch (err) {
      setError(err.message || "Failed to load audit events");
    } finally {
      setLoading(false);
    }
  }

  function handleExportCsv() {
    const url = getAuditExportUrl({
      action: actionFilter || null,
      resourceType: resourceTypeFilter || null,
      success: successFilter !== "" ? successFilter === "true" : null,
    });
    window.open(url, "_blank");
  }

  const actionColors = {
    MODEL_UPLOADED: "bg-emerald-100 text-emerald-800 border-emerald-200",
    MODEL_ACTIVATED: "bg-teal-100 text-teal-800 border-teal-200",
    MODEL_DELETED: "bg-rose-100 text-rose-800 border-rose-200",
    DEPLOYMENT_CREATED: "bg-blue-100 text-blue-800 border-blue-200",
    DEPLOYMENT_SCALED: "bg-indigo-100 text-indigo-800 border-indigo-200",
    DEPLOYMENT_STOPPED: "bg-amber-100 text-amber-800 border-amber-200",
    DEPLOYMENT_DELETED: "bg-rose-100 text-rose-800 border-rose-200",
    LOGIN_SUCCEEDED: "bg-green-100 text-green-800 border-green-200",
    LOGIN_FAILED: "bg-red-100 text-red-800 border-red-200",
    LOGOUT: "bg-slate-100 text-slate-800 border-slate-200",
    USER_CREATED: "bg-purple-100 text-purple-800 border-purple-200",
    USER_UPDATED: "bg-sky-100 text-sky-800 border-sky-200",
    USER_DELETED: "bg-orange-100 text-orange-800 border-orange-200",
    AUTOSCALING_CONFIG_UPDATED: "bg-cyan-100 text-cyan-800 border-cyan-200",
    EXPERIMENT_RUN: "bg-violet-100 text-violet-800 border-violet-200",
  };

  const totalPages = Math.ceil(total / limit);

  return (
    <div className="space-y-6">
      {/* Header Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
        <div>
          <h2 className="text-xl font-bold text-slate-900">Platform Security & Audit Logs</h2>
          <p className="text-sm text-slate-500 mt-0.5">
            Immutable tracking of state-changing operations, deployments, model updates, and authentication attempts.
          </p>
        </div>
        <div className="flex items-center space-x-3">
          <button
            type="button"
            onClick={loadEvents}
            className="px-3.5 py-2 text-sm text-slate-700 bg-slate-100 hover:bg-slate-200 font-medium rounded-lg transition"
          >
            Refresh
          </button>
          <button
            type="button"
            onClick={handleExportCsv}
            className="px-4 py-2 text-sm text-indigo-700 bg-indigo-50 hover:bg-indigo-100 border border-indigo-200 font-medium rounded-lg shadow-sm transition flex items-center space-x-1.5"
          >
            <span>📥</span>
            <span>Export CSV</span>
          </button>
        </div>
      </div>

      {error && (
        <div className="p-4 bg-rose-50 border border-rose-200 text-rose-700 text-sm rounded-xl">
          {error}
        </div>
      )}

      {/* Filters */}
      <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div>
          <label className="block text-xs font-semibold text-slate-600 uppercase mb-1">
            Action Filter
          </label>
          <select
            value={actionFilter}
            onChange={(e) => {
              setActionFilter(e.target.value);
              setPage(0);
            }}
            className="w-full text-sm border border-slate-300 rounded-lg p-2 focus:ring-2 focus:ring-indigo-500"
          >
            <option value="">All Actions</option>
            <option value="LOGIN_SUCCEEDED">LOGIN_SUCCEEDED</option>
            <option value="LOGIN_FAILED">LOGIN_FAILED</option>
            <option value="LOGOUT">LOGOUT</option>
            <option value="MODEL_UPLOADED">MODEL_UPLOADED</option>
            <option value="MODEL_ACTIVATED">MODEL_ACTIVATED</option>
            <option value="MODEL_DELETED">MODEL_DELETED</option>
            <option value="DEPLOYMENT_CREATED">DEPLOYMENT_CREATED</option>
            <option value="DEPLOYMENT_SCALED">DEPLOYMENT_SCALED</option>
            <option value="DEPLOYMENT_STOPPED">DEPLOYMENT_STOPPED</option>
            <option value="DEPLOYMENT_DELETED">DEPLOYMENT_DELETED</option>
            <option value="AUTOSCALING_CONFIG_UPDATED">AUTOSCALING_CONFIG_UPDATED</option>
            <option value="EXPERIMENT_RUN">EXPERIMENT_RUN</option>
            <option value="USER_CREATED">USER_CREATED</option>
            <option value="USER_UPDATED">USER_UPDATED</option>
            <option value="USER_DELETED">USER_DELETED</option>
          </select>
        </div>

        <div>
          <label className="block text-xs font-semibold text-slate-600 uppercase mb-1">
            Resource Type
          </label>
          <select
            value={resourceTypeFilter}
            onChange={(e) => {
              setResourceTypeFilter(e.target.value);
              setPage(0);
            }}
            className="w-full text-sm border border-slate-300 rounded-lg p-2 focus:ring-2 focus:ring-indigo-500"
          >
            <option value="">All Resource Types</option>
            <option value="model">model</option>
            <option value="deployment">deployment</option>
            <option value="user">user</option>
            <option value="auth">auth</option>
          </select>
        </div>

        <div>
          <label className="block text-xs font-semibold text-slate-600 uppercase mb-1">
            Result Status
          </label>
          <select
            value={successFilter}
            onChange={(e) => {
              setSuccessFilter(e.target.value);
              setPage(0);
            }}
            className="w-full text-sm border border-slate-300 rounded-lg p-2 focus:ring-2 focus:ring-indigo-500"
          >
            <option value="">All Results</option>
            <option value="true">Success only</option>
            <option value="false">Failure only</option>
          </select>
        </div>
      </div>

      {/* Audit Table */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        {loading ? (
          <div className="p-8 text-center text-slate-500">Loading audit records...</div>
        ) : events.length === 0 ? (
          <div className="p-8 text-center text-slate-500">No audit events match the selected criteria.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm text-slate-600">
              <thead className="bg-slate-50 border-b border-slate-200 text-xs font-semibold uppercase tracking-wider text-slate-500">
                <tr>
                  <th className="px-5 py-3.5">Timestamp</th>
                  <th className="px-5 py-3.5">Action</th>
                  <th className="px-5 py-3.5">User</th>
                  <th className="px-5 py-3.5">Resource</th>
                  <th className="px-5 py-3.5">Result</th>
                  <th className="px-5 py-3.5">IP Address</th>
                  <th className="px-5 py-3.5 text-right">Details</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {events.map((evt) => {
                  const isExpanded = expandedRow === evt.id;
                  let parsedDetails = null;
                  if (evt.details) {
                    try {
                      parsedDetails = JSON.parse(evt.details);
                    } catch {
                      parsedDetails = evt.details;
                    }
                  }

                  return (
                    <tr key={evt.id} className="hover:bg-slate-50/70 transition">
                      <td className="px-5 py-3.5 text-xs text-slate-500 whitespace-nowrap">
                        {new Date(evt.timestamp).toLocaleString()}
                      </td>
                      <td className="px-5 py-3.5">
                        <span
                          className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border ${
                            actionColors[evt.action] || "bg-slate-100 text-slate-700 border-slate-200"
                          }`}
                        >
                          {evt.action}
                        </span>
                      </td>
                      <td className="px-5 py-3.5">
                        <div className="text-xs font-medium text-slate-800">
                          {evt.user_email || "System / Dev"}
                        </div>
                        {evt.user_id && (
                          <div className="text-[10px] text-slate-400 font-mono">
                            {evt.user_id.substring(0, 8)}...
                          </div>
                        )}
                      </td>
                      <td className="px-5 py-3.5 text-xs">
                        <span className="font-semibold text-slate-700">{evt.resource_type}</span>
                        {evt.resource_id && (
                          <span className="text-slate-400 font-mono text-[11px] block truncate max-w-[140px]">
                            {evt.resource_id}
                          </span>
                        )}
                      </td>
                      <td className="px-5 py-3.5">
                        <span
                          className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                            evt.success
                              ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                              : "bg-rose-50 text-rose-700 border border-rose-200"
                          }`}
                        >
                          {evt.success ? "Success" : "Failed"}
                        </span>
                      </td>
                      <td className="px-5 py-3.5 text-xs text-slate-500 font-mono">
                        {evt.ip_address || "—"}
                      </td>
                      <td className="px-5 py-3.5 text-right">
                        {parsedDetails ? (
                          <button
                            type="button"
                            onClick={() => setExpandedRow(isExpanded ? null : evt.id)}
                            className="text-xs text-indigo-600 hover:text-indigo-800 font-medium underline"
                          >
                            {isExpanded ? "Hide" : "View"}
                          </button>
                        ) : (
                          <span className="text-slate-400 text-xs">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* Expandable details drawer */}
        {expandedRow && (
          <div className="p-4 bg-slate-900 text-slate-100 border-t border-slate-800 text-xs font-mono overflow-x-auto">
            <div className="flex justify-between items-center mb-2">
              <span className="text-slate-400 uppercase text-[10px] font-bold">Audit Event Payload Details</span>
              <button
                type="button"
                onClick={() => setExpandedRow(null)}
                className="text-slate-400 hover:text-white"
              >
                ✕ Close
              </button>
            </div>
            <pre className="whitespace-pre-wrap">
              {JSON.stringify(
                JSON.parse(events.find((e) => e.id === expandedRow)?.details || "{}"),
                null,
                2
              )}
            </pre>
          </div>
        )}

        {/* Pagination Bar */}
        <div className="px-5 py-3.5 bg-slate-50 border-t border-slate-200 flex items-center justify-between text-xs text-slate-600">
          <div>
            Showing <span className="font-semibold">{events.length}</span> of{" "}
            <span className="font-semibold">{total}</span> events
          </div>
          <div className="flex items-center space-x-2">
            <button
              type="button"
              disabled={page === 0}
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              className="px-2.5 py-1 bg-white border border-slate-300 rounded font-medium disabled:opacity-40"
            >
              Previous
            </button>
            <span>
              Page {page + 1} of {Math.max(1, totalPages)}
            </span>
            <button
              type="button"
              disabled={page + 1 >= totalPages}
              onClick={() => setPage((p) => p + 1)}
              className="px-2.5 py-1 bg-white border border-slate-300 rounded font-medium disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
