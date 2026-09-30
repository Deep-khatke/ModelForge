import { useState } from "react";
import { loginUser, registerUser } from "../api/client";

export default function LoginModal({ isOpen, onClose, onLoginSuccess }) {
  const [isRegister, setIsRegister] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  if (!isOpen) return null;

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);

    try {
      let result;
      if (isRegister) {
        if (!displayName.trim()) {
          setError("Display name is required.");
          setSubmitting(false);
          return;
        }
        result = await registerUser(email.trim(), password, displayName.trim());
      } else {
        result = await loginUser(email.trim(), password);
      }

      onLoginSuccess(result.user);
      onClose();
    } catch (err) {
      setError(err.message || "Authentication failed. Please check credentials.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-sm p-4">
      <div className="bg-white rounded-2xl border border-slate-200 shadow-2xl w-full max-w-md overflow-hidden">
        {/* Header */}
        <div className="bg-gradient-to-r from-slate-900 to-indigo-950 px-6 py-5 text-white flex justify-between items-center">
          <div>
            <h2 className="text-xl font-bold tracking-tight">
              {isRegister ? "Create ModelForge Account" : "Sign In to ModelForge"}
            </h2>
            <p className="text-xs text-indigo-200 mt-0.5">
              {isRegister ? "Register for platform access" : "Enter your credentials to manage deployments"}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-slate-400 hover:text-white rounded-lg p-1.5 transition text-lg"
          >
            ✕
          </button>
        </div>

        {/* Form Body */}
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {error && (
            <div className="p-3 bg-rose-50 border border-rose-200 text-rose-700 text-sm rounded-lg flex items-start space-x-2">
              <span className="font-bold text-rose-500">⚠</span>
              <span>{error}</span>
            </div>
          )}

          {isRegister && (
            <div>
              <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wide mb-1">
                Display Name
              </label>
              <input
                type="text"
                required
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                placeholder="e.g. Alice ML Ops"
                className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
              />
            </div>
          )}

          <div>
            <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wide mb-1">
              Email Address
            </label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="e.g. admin@modelforge.local"
              className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wide mb-1">
              Password
            </label>
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
            />
          </div>

          <div className="pt-2">
            <button
              type="submit"
              disabled={submitting}
              className="w-full py-2.5 px-4 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white font-medium text-sm rounded-lg shadow-sm transition flex items-center justify-center space-x-2"
            >
              {submitting ? (
                <span>Authenticating...</span>
              ) : (
                <span>{isRegister ? "Register & Sign In" : "Sign In"}</span>
              )}
            </button>
          </div>

          {/* Development Bootstrap Helper Note */}
          <div className="rounded-lg bg-slate-50 border border-slate-200 p-3 text-xs text-slate-600">
            <p className="font-semibold text-slate-700 mb-0.5">Initial Administrator Access</p>
            <p>
              Default Email: <code className="bg-white px-1.5 py-0.5 border rounded text-slate-800">admin@modelforge.local</code>
            </p>
            <p className="mt-0.5">
              Default Pass: <code className="bg-white px-1.5 py-0.5 border rounded text-slate-800">Admin123!</code>
            </p>
          </div>

          <div className="text-center pt-1">
            <button
              type="button"
              onClick={() => {
                setIsRegister(!isRegister);
                setError(null);
              }}
              className="text-xs text-indigo-600 hover:text-indigo-800 font-medium"
            >
              {isRegister
                ? "Already have an account? Sign In"
                : "Need a new account? Register"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
