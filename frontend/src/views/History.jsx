import React, { useEffect, useState } from "react";
import { api, notifyPendingChanged } from "../api";

const TEXT_KINDS = new Set(["markdown", "yaml", "toml"]);

export default function History() {
  const [path, setPath] = useState("");
  const [tree, setTree] = useState([]); // text files from /api/tree
  const [history, setHistory] = useState(null);
  const [error, setError] = useState("");
  const [version, setVersion] = useState(null); // {sha, content}
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api("/api/tree")
      .then((d) => {
        const files = (d.entries || [])
          .filter((e) => TEXT_KINDS.has(e.kind))
          .map((e) => e.path)
          .sort();
        setTree(files);
      })
      .catch(() => setTree([]));
  }, []);

  const load = async (p) => {
    const target = p || path;
    setError("");
    setSaved(false);
    setVersion(null);
    if (!target.trim() || target.trim() === "/") {
      setError("Izaberi konkretan fajl iz liste — direktorijumi nemaju prikaz sadržaja.");
      return;
    }
    try {
      const data = await api(`/api/history?path=${encodeURIComponent(target)}`);
      setHistory(data);
      if (p) setPath(p);
    } catch (err) {
      setError(err.message);
    }
  };

  const showVersion = async (sha) => {
    setError("");
    if (!path) {
      setError("Prvo izaberi fajl iz liste.");
      return;
    }
    try {
      const file = await api(`/api/file?path=${encodeURIComponent(path)}&ref=${sha}`);
      setVersion({ sha, ...file });
    } catch (err) {
      setError(err.message);
    }
  };

  const rollback = async () => {
    if (!version) return;
    setError("");
    try {
      const current = await api(`/api/file?path=${encodeURIComponent(path)}`);
      await api("/api/pending", {
        method: "POST",
        json: {
          ops: [
            {
              op: "update",
              path,
              content: version.content,
              sha: current.sha,
            },
          ],
        },
      });
      setSaved(true);
      notifyPendingChanged();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div>
      <div className="page-head">
        <h1>Istorija fajlova</h1>
      </div>

      <div className="panel filter-bar">
        <select
          className="text-input grow"
          value={path}
          onChange={(e) => {
            const value = e.target.value;
            setPath(value);
            load(value);
          }}
        >
          <option value="">Izaberi fajl iz repozitorijuma...</option>
          {tree.map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
        <button className="button" disabled={!path} onClick={() => load()}>Prikaži istoriju</button>
      </div>

      {error && <div className="panel error-box"><p className="error-text">{error}</p></div>}
      {saved && <div className="success-box">Stara verzija je dodata u pending kao izmena — potvrdi je u „Preview & Commit".</div>}

      {history && (
        <div className="two-col">
          <div className="panel table-panel">
            <h3>Commit-ovi za: <code>{history.path}</code></h3>
            <table className="data-table">
              <thead>
                <tr><th>Datum</th><th>Poruka</th><th>Autor</th><th></th></tr>
              </thead>
              <tbody>
                {(history.commits || []).map((c) => (
                  <tr key={c.sha}>
                    <td>{new Date(c.date).toLocaleString("sr-RS")}</td>
                    <td>{c.message.split("\n")[0]}</td>
                    <td>{c.author}</td>
                    <td><button className="button tiny" onClick={() => showVersion(c.sha)}>Pogledaj</button></td>
                  </tr>
                ))}
                {(!history.commits || history.commits.length === 0) && (
                  <tr><td colSpan={4} className="empty-cell">Nema commit-ova za ovu putanju.</td></tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="panel">
            <h3>Stara verzija {version && <code>{version.sha.slice(0, 10)}</code>}</h3>
            {version ? (
              <>
                <pre className="file-preview">{version.content || "binarni fajl"}</pre>
                <div className="button-row">
                  <button className="button primary" disabled={version.binary} onClick={rollback}>↺ Vrati ovu verziju (u pending)</button>
                </div>
                <p className="hint">Vraćanje kreira NOVI commit sa starim sadržajem — nikad force-push; CI će automatski redeployovati.</p>
              </>
            ) : (
              <p className="empty-cell">Izaberi commit da vidiš sadržaj fajla.</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
