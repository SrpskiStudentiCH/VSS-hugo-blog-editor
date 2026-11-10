import React, { useEffect, useState } from "react";
import { api, fileToBase64, notifyPendingChanged } from "../api";
import { ErrorBox, Loading } from "../components/Shared";

const LANGS = ["sr", "en", "de"];
const EMPTY_DOC = { type: "", title: "", desc: "", year: "", url: "" };

export default function Documents() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [docs, setDocs] = useState([]); // merged by index: per:{lang:{...}}
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = () => {
    setError("");
    api("/api/docs").then(setData).catch((err) => setError(err.message));
  };

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    if (!data) return;
    const max = Math.max(...LANGS.map((l) => data.languages[l]?.docs?.length || 0), 0);
    const merged = Array.from({ length: max }, (_, i) => ({
      type: "",
      title: "",
      desc: "",
      year: "",
      url: "",
      per: {},
    }));
    LANGS.forEach((lang) => {
      const item = data.languages[lang];
      (item?.docs || []).forEach((d, i) => {
        merged[i].per[lang] = {
          type: d.type || "",
          title: d.title || "",
          desc: d.desc || "",
          year: d.year != null ? String(d.year) : "",
          url: d.url || "",
        };
      });
    });
    setDocs(merged);
  }, [data]);

  const updatePer = (index, lang, field, value) =>
    setDocs((prev) =>
      prev.map((d, i) =>
        i === index
          ? { ...d, per: { ...d.per, [lang]: { ...(d.per[lang] || EMPTY_DOC), [field]: value } } }
          : d
      )
    );

  const uploadPdf = async (file) => {
    if (!file) return;
    const b64 = await fileToBase64(file);
    const name = file.name
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9.]+/g, "-")
      .replace(/^-+|-+$/g, "");
    await api("/api/pending", {
      method: "POST",
      json: {
        ops: [{ op: "create", path: `static/documents/${name}`, content_b64: b64 }],
      },
    });
    notifyPendingChanged();
    return `/documents/${name}`;
  };

  const handleUpload = async (e, index) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setBusy(true);
    try {
      const url = await uploadPdf(file);
      LANGS.forEach((lang) => updatePer(index, lang, "url", url));
    } catch (err) {
      alert(err.message);
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    setError("");
    setSaved(false);
    const languages = {};
    LANGS.forEach((lang) => {
      languages[lang] = {
        docs: docs
          .filter((d) => (d.per[lang]?.title || "").trim())
          .map((d) => {
            const p = d.per[lang];
            const out = {
              type: p.type || "document",
              title: p.title,
              desc: p.desc || "",
              year: p.year ? Number(p.year) : new Date().getFullYear(),
            };
            if (p.url) out.url = p.url;
            return out;
          }),
      };
    });
    try {
      await api("/api/pending/docs", { method: "POST", json: { languages } });
      setSaved(true);
      notifyPendingChanged();
    } catch (err) {
      setError(Array.isArray(err.details?.errors) ? err.details.errors.join(" | ") : err.message);
    }
  };

  if (error && !data) return <ErrorBox message={error} onRetry={load} />;
  if (!data) return <Loading />;

  return (
    <div>
      <div className="page-head">
        <h1>Dokumenta</h1>
        <div className="button-row">
          <button className="button" onClick={() => setDocs((p) => [...p, { type: "", title: "", desc: "", year: "", url: "", per: {} }])}>
            ＋ Dodaj dokument
          </button>
          <button className="button primary" onClick={save}>Sačuvaj u pending</button>
        </div>
      </div>

      {error && <div className="panel error-box"><p className="error-text">{error}</p></div>}
      {saved && <div className="success-box">Dokumenta su u pending sloju.</div>}

      <p className="hint">
        Dokument bez URL-a se prikazuje kao „uskoro". PDF se uploaduje u static/documents/ i URL se
        unosi kao /documents/ime.pdf. Upload PDF-a se dodaje u pending zajedno sa izmenama.
      </p>

      <div className="panel">
        {docs.map((d, i) => (
          <div key={i} className="doc-block">
            <div className="doc-head">
              <strong>Dokument {i + 1}</strong>
              <div className="button-row compact">
                <label className="button small">📄 Upload PDF
                  <input type="file" accept=".pdf" hidden disabled={busy} onChange={(e) => handleUpload(e, i)} />
                </label>
                <button className="button small danger" onClick={() => setDocs((p) => p.filter((_, j) => j !== i))}>✕ Ukloni</button>
              </div>
            </div>
            <div className="lang-columns">
              {LANGS.map((lang) => {
                const p = d.per[lang] || EMPTY_DOC;
                return (
                  <div key={lang} className="lang-col">
                    <h4>{lang.toUpperCase()}</h4>
                    <label>Tip <input className="text-input" value={p.type} onChange={(e) => updatePer(i, lang, "type", e.target.value)} /></label>
                    <label>Naslov <input className="text-input" value={p.title} onChange={(e) => updatePer(i, lang, "title", e.target.value)} /></label>
                    <label>Opis <textarea className="text-input" rows={2} value={p.desc} onChange={(e) => updatePer(i, lang, "desc", e.target.value)} /></label>
                    <label>Godina <input className="text-input" value={p.year} onChange={(e) => updatePer(i, lang, "year", e.target.value)} /></label>
                    <label>URL (prazno = „uskoro") <input className="text-input" value={p.url} onChange={(e) => updatePer(i, lang, "url", e.target.value)} /></label>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
        {docs.length === 0 && <p className="empty-cell">Nema dokumenata.</p>}
      </div>
    </div>
  );
}
