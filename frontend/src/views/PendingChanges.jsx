import React, { useEffect, useState } from "react";
import { api, notifyPendingChanged } from "../api";
import { ConfirmDialog, DiffView, ErrorBox, Loading } from "../components/Shared";

const OP_LABELS = { create: "kreira", update: "menja", delete: "briše" };

export default function PendingChanges() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [confirmClear, setConfirmClear] = useState(false);

  const load = () => {
    setError("");
    api("/api/pending").then(setData).catch((err) => setError(err.message));
  };

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    if (data && !message) setMessage(data.commit_message || "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  const commit = async () => {
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const res = await api("/api/commit", { method: "POST", json: { message } });
      setResult(res);
      notifyPendingChanged();
      load();
    } catch (err) {
      if (err.conflict) {
        setError(`${err.message} Osveži podatke (dugme ispod) i ponovo dodaj izmene.`);
      } else {
        setError(err.message);
      }
    } finally {
      setBusy(false);
    }
  };

  const removeOp = async (id) => {
    await api(`/api/pending?op=${id}`, { method: "DELETE" });
    notifyPendingChanged();
    load();
  };

  const clearAll = async () => {
    await api("/api/pending", { method: "DELETE" });
    setConfirmClear(false);
    notifyPendingChanged();
    load();
  };

  if (error && !data) return <ErrorBox message={error} onRetry={load} />;
  if (!data) return <Loading />;

  const ops = data.ops || [];

  return (
    <div>
      <div className="page-head">
        <h1>Preview & Commit</h1>
        <div className="button-row">
          <button className="button" onClick={load}>↻ Osveži</button>
          {ops.length > 0 && (
            <button className="button danger" onClick={() => setConfirmClear(true)}>Obriši sve izmene</button>
          )}
        </div>
      </div>

      {error && <div className="panel error-box"><p className="error-text">{error}</p></div>}
      {result && (
        <div className="success-box">
          Commit uspešan: <code>{result.sha.slice(0, 10)}</code> — „{result.message}". GitHub Actions će automatski deployovati sajt.
        </div>
      )}

      {ops.length === 0 && (
        <div className="panel">
          <p className="empty-cell">Nema izmena u pending sloju. Sve izmene iz editora dolaze ovde pre nego što se pošalju na GitHub.</p>
        </div>
      )}

      {ops.map((op) => (
        <div key={op.id} className={`panel op-card op-${op.op}`}>
          <div className="op-head">
            <span className={`tag op-${op.op}`}>{OP_LABELS[op.op] || op.op}</span>
            <code>{op.path}</code>
            <button className="button tiny danger" onClick={() => removeOp(op.id)}>✕</button>
          </div>
          {op.binary ? (
            <p className="hint">Binarni fajl ({op.size} bajtova) — sadržaj se prikazuje kao base64.</p>
          ) : (
            <DiffView ops={op.diff} />
          )}
        </div>
      ))}

      {ops.length > 0 && (
        <div className="panel commit-panel">
          <h2>Commit poruka</h2>
          <input className="text-input grow" value={message} onChange={(e) => setMessage(e.target.value)} />
          <p className="hint">
            Svi fajlovi idu u JEDAN atomični commit na granu „main" (Git Data API: blobs → tree → commit → ref).
            Pre commita se ponovo proverava HEAD grane — ako se promenio, dobićeš upozorenje o konfliktu.
          </p>
          <button className="button primary big" disabled={busy || !message.trim()} onClick={commit}>
            {busy ? "Commit..." : `✓ Commit (${ops.length} fajlova)`}
          </button>
        </div>
      )}

      {confirmClear && (
        <ConfirmDialog
          title="Obriši sve pending izmene?"
          message="Sve nekomitovane izmene će biti izgubljene."
          confirmText="Obriši sve"
          onConfirm={clearAll}
          onCancel={() => setConfirmClear(false)}
        />
      )}
    </div>
  );
}
