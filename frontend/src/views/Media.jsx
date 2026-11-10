import React, { useEffect, useMemo, useRef, useState } from "react";
import { api, fileToBase64, imageUrl, notifyPendingChanged } from "../api";
import { ConfirmDialog, ErrorBox, Loading } from "../components/Shared";

const IMAGE_EXT_RE = /\.(jpe?g|png|webp|gif)$/i;
const DOC_EXT_RE = /\.pdf$/i;

export default function Media() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [folder, setFolder] = useState("all");
  const [onlyUnused, setOnlyUnused] = useState(false);
  const [selected, setSelected] = useState(null); // path of selected image
  const [confirmDelete, setConfirmDelete] = useState(null); // path
  const [busy, setBusy] = useState(false);
  const fileRef = useRef(null);

  const load = () => {
    setError("");
    api("/api/media").then(setData).catch((err) => setError(err.message));
  };

  useEffect(() => {
    load();
  }, []);

  const folders = useMemo(() => {
    if (!data) return [];
    const set = new Set();
    data.images.forEach((img) => {
      const parts = img.path.split("/");
      parts.pop();
      set.add(parts.join("/"));
    });
    return ["all", ...Array.from(set).sort()];
  }, [data]);

  const filtered = useMemo(() => {
    if (!data) return [];
    return data.images.filter((img) => {
      if (folder !== "all" && !img.path.startsWith(folder + "/")) return false;
      if (onlyUnused && (img.referenced_by || []).length > 0) return false;
      return true;
    });
  }, [data, folder, onlyUnused]);

  const uploadTo = async (file, targetPath) => {
    if (!file) return;
    const isImage = IMAGE_EXT_RE.test(file.name);
    const isDoc = DOC_EXT_RE.test(file.name);
    if (!isImage && !isDoc) {
      alert("Dozvoljeni su samo JPG/PNG/WEBP/GIF i PDF fajlovi.");
      return;
    }
    const b64 = await fileToBase64(file);
    const target =
      targetPath ||
      (isDoc
        ? `static/documents/${sanitizeName(file.name)}`
        : `static/images/${folder === "all" ? "events" : folder.replace(/^static\//, "")}/${sanitizeName(file.name)}`);
    const op = {
      op: targetPath ? "update" : "create",
      path: target,
      content_b64: b64,
    };
    if (targetPath) {
      const existing = data.images.find((img) => img.path === targetPath);
      op.sha = existing?.sha;
    }
    try {
      await api("/api/pending", { method: "POST", json: { ops: [op] } });
      notifyPendingChanged();
      load();
    } catch (err) {
      alert(err.message);
    }
  };

  const handleFile = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (DOC_EXT_RE.test(file.name)) {
      await uploadTo(file, null);
      return;
    }
    setBusy(true);
    try {
      await uploadTo(file, null);
    } finally {
      setBusy(false);
    }
  };

  const doDelete = async () => {
    if (!confirmDelete) return;
    const img = data.images.find((i) => i.path === confirmDelete);
    try {
      await api("/api/pending", {
        method: "POST",
        json: { ops: [{ op: "delete", path: confirmDelete, sha: img?.sha }] },
      });
      notifyPendingChanged();
      setConfirmDelete(null);
      load();
    } catch (err) {
      alert(err.message);
      setConfirmDelete(null);
    }
  };

  if (error) return <ErrorBox message={error} onRetry={load} />;
  if (!data) return <Loading />;

  const selectedImg = selected ? data.images.find((i) => i.path === selected) : null;

  return (
    <div>
      <div className="page-head">
        <h1>Fotografije</h1>
        <div className="button-row">
          <button className="button primary" disabled={busy} onClick={() => fileRef.current?.click()}>
            {busy ? "Učitavam..." : "＋ Upload slike / PDF-a"}
          </button>
          <input ref={fileRef} type="file" accept=".jpg,.jpeg,.png,.webp,.gif,.pdf" hidden onChange={handleFile} />
        </div>
      </div>

      <div className="panel filter-bar">
        <select value={folder} onChange={(e) => setFolder(e.target.value)}>
          {folders.map((f) => <option key={f} value={f}>{f === "all" ? "Svi folderi" : f}</option>)}
        </select>
        <label className="checkbox-label">
          <input type="checkbox" checked={onlyUnused} onChange={(e) => setOnlyUnused(e.target.checked)} />
          Samo neiskorišćene (kandidati za čišćenje)
        </label>
        <span className="hint">Upload ide u izabrani folder; za PDF izaberi folder static/documents.</span>
      </div>

      <div className="image-grid">
        {filtered.map((img) => {
          const refs = img.referenced_by || [];
          return (
            <div key={img.path} className={`image-card ${refs.length ? "" : "unused"}`} onClick={() => setSelected(img.path)}>
              {/\.pdf$/i.test(img.path) ? (
                <div className="pdf-placeholder">PDF</div>
              ) : (
                <img src={imageUrl(img.path)} alt={img.path} loading="lazy" />
              )}
              <div className="image-meta">
                <span className="image-name">{img.path}</span>
                <span className="image-size">{formatSize(img.size)}</span>
                <span className={refs.length ? "tag published" : "tag unused"}>
                  {refs.length ? `koristi se (${refs.length})` : "neiskorišćena"}
                </span>
              </div>
            </div>
          );
        })}
        {filtered.length === 0 && <p className="empty-cell">Nema slika u ovom folderu.</p>}
      </div>

      {selectedImg && (
        <div className="panel detail-panel">
          <h3>{selectedImg.path}</h3>
          <div className="button-row">
            <button
              className="button"
              onClick={() => {
                const input = document.createElement("input");
                input.type = "file";
                input.accept = "image/*";
                input.onchange = async (ev) => {
                  const f = ev.target.files?.[0];
                  if (f) await uploadTo(f, selectedImg.path);
                };
                input.click();
              }}
            >
              Zameni (PUT na isti path)
            </button>
            <button
              className="button danger"
              disabled={(selectedImg.referenced_by || []).length > 0}
              title={(selectedImg.referenced_by || []).length ? "Brisanje onemogućeno — slika je referencirana" : ""}
              onClick={() => setConfirmDelete(selectedImg.path)}
            >
              Obriši
            </button>
          </div>
          {(selectedImg.referenced_by || []).length > 0 && (
            <>
              <p className="hint">Referencirana iz:</p>
              <ul className="ref-list">
                {selectedImg.referenced_by.map((p) => <li key={p}><code>{p}</code></li>)}
              </ul>
            </>
          )}
          <p className="hint">Zamena upisuje novu sliku na istu putanju — svi fajlovi koji je referenciraju odmah vide novu verziju.</p>
        </div>
      )}

      {confirmDelete && (
        <ConfirmDialog
          title="Obriši fajl?"
          message={`Fajl "${confirmDelete}" biće uklonjen iz repozitorijuma.`}
          confirmText="Obriši"
          confirmWord="OBRIŠI"
          onConfirm={doDelete}
          onCancel={() => setConfirmDelete(null)}
        />
      )}
    </div>
  );
}

function sanitizeName(name) {
  return (
    name
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9.]+/g, "-")
      .replace(/^-+|-+$/g, "")
  );
}

function formatSize(bytes) {
  if (bytes == null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
