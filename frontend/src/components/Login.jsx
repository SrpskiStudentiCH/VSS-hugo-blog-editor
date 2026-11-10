import React, { useState } from "react";
import { login } from "../api";

const Login = ({ onLogin }) => {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const data = await login(username, password);
      if (data.success) onLogin(data.token);
      else setError(data.error || "Login failed");
    } catch (err) {
      setError(err.message || "Cannot reach server");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-container">
      <div className="login-card">
        <h2>VSS Admin — prijava</h2>
        <form onSubmit={handleSubmit}>
          <label>Korisničko ime</label>
          <input type="text" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
          <label>Lozinka</label>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
          <button type="submit" disabled={busy}>{busy ? "Prijava..." : "Prijavi se"}</button>
        </form>
        {error && <p className="error-text">{error}</p>}
      </div>
    </div>
  );
};

export default Login;
