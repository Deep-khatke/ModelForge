import { useState, useEffect } from "react";
import { fetchUsers, createUser, updateUser, deleteUser } from "../api/client";

export default function UserManagement({ currentUser }) {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  // New user form state
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newEmail, setNewEmail] = useState("");
  const [newDisplayName, setNewDisplayName] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newRole, setNewRole] = useState("OPERATOR");
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    loadUsers();
  }, []);

  async function loadUsers() {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchUsers();
      setUsers(data);
    } catch (err) {
      setError(err.message || "Failed to load users");
    } finally {
      setLoading(false);
    }
  }

  async function handleCreateUser(e) {
    e.preventDefault();
    setCreating(true);
    setError(null);
    setSuccess(null);
    try {
      await createUser({
        email: newEmail.trim(),
        displayName: newDisplayName.trim(),
        password: newPassword,
        role: newRole,
      });
      setSuccess(`User "${newEmail}" created successfully.`);
      setShowCreateModal(false);
      setNewEmail("");
      setNewDisplayName("");
      setNewPassword("");
      setNewRole("OPERATOR");
      loadUsers();
    } catch (err) {
      setError(err.message || "Failed to create user");
    } finally {
      setCreating(false);
    }
  }

  async function handleRoleChange(user, role) {
    setError(null);
    setSuccess(null);
    try {
      await updateUser(user.id, { role });
      setSuccess(`Updated role for ${user.email} to ${role}.`);
      loadUsers();
    } catch (err) {
      setError(err.message || "Failed to update user role");
    }
  }

  async function handleToggleActive(user) {
    if (user.id === currentUser?.id) {
      setError("Cannot deactivate your own account.");
      return;
    }
    setError(null);
    setSuccess(null);
    try {
      const updatedStatus = !user.is_active;
      await updateUser(user.id, { is_active: updatedStatus });
      setSuccess(`Account ${user.email} is now ${updatedStatus ? "active" : "inactive"}.`);
      loadUsers();
    } catch (err) {
      setError(err.message || "Failed to update user status");
    }
  }

  async function handleDeleteUser(user) {
    if (user.id === currentUser?.id) {
      setError("Cannot delete your own account.");
      return;
    }
    if (!window.confirm(`Are you sure you want to delete user ${user.email}?`)) {
      return;
    }
    setError(null);
    setSuccess(null);
    try {
      await deleteUser(user.id);
      setSuccess(`Deleted user ${user.email}.`);
      loadUsers();
    } catch (err) {
      setError(err.message || "Failed to delete user");
    }
  }

  const roleColors = {
    ADMIN: "bg-purple-100 text-purple-800 border-purple-200",
    OPERATOR: "bg-blue-100 text-blue-800 border-blue-200",
    VIEWER: "bg-slate-100 text-slate-800 border-slate-200",
  };

  return (
    <div className="space-y-6">
      {/* Header bar */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
        <div>
          <h2 className="text-xl font-bold text-slate-900">User Management & Access Control</h2>
          <p className="text-sm text-slate-500 mt-0.5">
            Administer user accounts, manage roles (ADMIN, OPERATOR, VIEWER), and deactivate credentials.
          </p>
        </div>
        <div className="flex items-center space-x-3">
          <button
            type="button"
            onClick={loadUsers}
            className="px-3.5 py-2 text-sm text-slate-700 bg-slate-100 hover:bg-slate-200 font-medium rounded-lg transition"
          >
            Refresh
          </button>
          <button
            type="button"
            onClick={() => setShowCreateModal(true)}
            className="px-4 py-2 text-sm text-white bg-indigo-600 hover:bg-indigo-700 font-medium rounded-lg shadow-sm transition"
          >
            + Add User
          </button>
        </div>
      </div>

      {error && (
        <div className="p-4 bg-rose-50 border border-rose-200 text-rose-700 text-sm rounded-xl flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-rose-500 hover:text-rose-700">✕</button>
        </div>
      )}

      {success && (
        <div className="p-4 bg-emerald-50 border border-emerald-200 text-emerald-700 text-sm rounded-xl flex items-center justify-between">
          <span>{success}</span>
          <button onClick={() => setSuccess(null)} className="text-emerald-500 hover:text-emerald-700">✕</button>
        </div>
      )}

      {/* Users Table */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        {loading ? (
          <div className="p-8 text-center text-slate-500">Loading user accounts...</div>
        ) : users.length === 0 ? (
          <div className="p-8 text-center text-slate-500">No user accounts found.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm text-slate-600">
              <thead className="bg-slate-50 border-b border-slate-200 text-xs font-semibold uppercase tracking-wider text-slate-500">
                <tr>
                  <th className="px-5 py-3.5">User</th>
                  <th className="px-5 py-3.5">Role</th>
                  <th className="px-5 py-3.5">Status</th>
                  <th className="px-5 py-3.5">Last Login</th>
                  <th className="px-5 py-3.5">Created</th>
                  <th className="px-5 py-3.5 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {users.map((u) => {
                  const isSelf = u.id === currentUser?.id;
                  return (
                    <tr key={u.id} className="hover:bg-slate-50/70 transition">
                      <td className="px-5 py-4">
                        <div className="font-medium text-slate-900 flex items-center space-x-2">
                          <span>{u.display_name}</span>
                          {isSelf && (
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 font-normal">
                              You
                            </span>
                          )}
                        </div>
                        <div className="text-xs text-slate-400 mt-0.5">{u.email}</div>
                      </td>
                      <td className="px-5 py-4">
                        <select
                          value={u.role}
                          onChange={(e) => handleRoleChange(u, e.target.value)}
                          disabled={isSelf}
                          className={`text-xs font-semibold px-2.5 py-1 rounded-full border ${
                            roleColors[u.role] || roleColors.VIEWER
                          } cursor-pointer disabled:cursor-not-allowed`}
                        >
                          <option value="ADMIN">ADMIN</option>
                          <option value="OPERATOR">OPERATOR</option>
                          <option value="VIEWER">VIEWER</option>
                        </select>
                      </td>
                      <td className="px-5 py-4">
                        <span
                          className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                            u.is_active
                              ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                              : "bg-rose-50 text-rose-700 border border-rose-200"
                          }`}
                        >
                          {u.is_active ? "Active" : "Inactive"}
                        </span>
                      </td>
                      <td className="px-5 py-4 text-xs text-slate-500">
                        {u.last_login_at
                          ? new Date(u.last_login_at).toLocaleString()
                          : "Never"}
                      </td>
                      <td className="px-5 py-4 text-xs text-slate-500">
                        {new Date(u.created_at).toLocaleDateString()}
                      </td>
                      <td className="px-5 py-4 text-right space-x-2">
                        <button
                          type="button"
                          onClick={() => handleToggleActive(u)}
                          disabled={isSelf}
                          className="text-xs font-medium text-slate-600 hover:text-slate-900 disabled:opacity-40 disabled:hover:text-slate-600 px-2 py-1 rounded border border-slate-200 hover:bg-slate-100 transition"
                        >
                          {u.is_active ? "Deactivate" : "Activate"}
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDeleteUser(u)}
                          disabled={isSelf}
                          className="text-xs font-medium text-rose-600 hover:text-rose-800 disabled:opacity-40 disabled:hover:text-rose-600 px-2 py-1 rounded border border-rose-200 hover:bg-rose-50 transition"
                        >
                          Delete
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Create User Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-sm p-4">
          <div className="bg-white rounded-2xl border border-slate-200 shadow-2xl w-full max-w-md overflow-hidden">
            <div className="bg-gradient-to-r from-slate-900 to-indigo-950 px-6 py-4 text-white flex justify-between items-center">
              <h3 className="text-lg font-bold">Add New User</h3>
              <button
                onClick={() => setShowCreateModal(false)}
                className="text-slate-400 hover:text-white text-lg"
              >
                ✕
              </button>
            </div>
            <form onSubmit={handleCreateUser} className="p-6 space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wide mb-1">
                  Display Name
                </label>
                <input
                  type="text"
                  required
                  value={newDisplayName}
                  onChange={(e) => setNewDisplayName(e.target.value)}
                  placeholder="e.g. Jane Doe"
                  className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wide mb-1">
                  Email Address
                </label>
                <input
                  type="email"
                  required
                  value={newEmail}
                  onChange={(e) => setNewEmail(e.target.value)}
                  placeholder="jane.doe@company.org"
                  className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wide mb-1">
                  Temporary Password
                </label>
                <input
                  type="password"
                  required
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder="Minimum 8 characters"
                  className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wide mb-1">
                  Assigned Role
                </label>
                <select
                  value={newRole}
                  onChange={(e) => setNewRole(e.target.value)}
                  className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                >
                  <option value="VIEWER">VIEWER (Read & Inference only)</option>
                  <option value="OPERATOR">OPERATOR (Deploy, scale, upload models)</option>
                  <option value="ADMIN">ADMIN (Full administrative privileges)</option>
                </select>
              </div>

              <div className="pt-2 flex justify-end space-x-3">
                <button
                  type="button"
                  onClick={() => setShowCreateModal(false)}
                  className="px-4 py-2 text-sm text-slate-600 hover:text-slate-800 font-medium"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={creating}
                  className="px-4 py-2 text-sm text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 font-medium rounded-lg shadow-sm"
                >
                  {creating ? "Creating..." : "Create User"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
