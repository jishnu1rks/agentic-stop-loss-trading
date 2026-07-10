import { useEffect, useState } from "react";
import { auth } from "../api/client";

export default function LoginGate({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<"checking" | "required" | "authenticated">("checking");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (auth.hasStoredCredentials()) {
      setStatus("authenticated");
      return;
    }
    auth.isRequired().then((required) => setStatus(required ? "required" : "authenticated"));
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    const ok = await auth.login(username, password);
    setSubmitting(false);
    if (ok) {
      setStatus("authenticated");
    } else {
      setError("Incorrect username or password.");
    }
  };

  if (status === "checking") {
    return null;
  }

  if (status === "required") {
    return (
      <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <form onSubmit={handleSubmit} className="panel" style={{ width: 320 }}>
          <h3 style={{ marginBottom: 4 }}>Sign in</h3>
          <p className="text-dim" style={{ fontSize: 13, marginBottom: 16 }}>
            Agentic Stop-Loss Trading
          </p>
          {error && <div className="error-banner">{error}</div>}
          <div className="form-field" style={{ marginBottom: 12 }}>
            <label>Username</label>
            <input
              autoFocus
              style={{ width: "100%" }}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
          </div>
          <div className="form-field" style={{ marginBottom: 16 }}>
            <label>Password</label>
            <input
              type="password"
              style={{ width: "100%" }}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          <button className="btn btn-buy" style={{ width: "100%" }} disabled={submitting} type="submit">
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    );
  }

  return <>{children}</>;
}
