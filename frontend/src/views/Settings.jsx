import React, { useEffect, useMemo, useState } from "react";
import { api, notifyPendingChanged } from "../api";
import { ErrorBox, Loading } from "../components/Shared";

const LANGS = ["sr", "en", "de"];

export default function Settings() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState("params");
  const [params, setParams] = useState({ description: "", brandLogo: "", ogImage: "", defaultImage: "", joinFormUrl: "" });
  const [contact, setContact] = useState({ email: "", linkedin: "", instagram: "" });
  const [i18nEdits, setI18nEdits] = useState({}); // { `${lang}:${key}`: value }
  const [i18nSearch, setI18nSearch] = useState("");
  const [saved, setSaved] = useState("");

  const load = () => {
    setError("");
    api("/api/settings").then((d) => {
      setData(d);
      setParams({ ...d.hugo.params.params });
      setContact({ ...d.hugo.params.contact });
    }).catch((err) => setError(err.message));
  };

  useEffect(() => {
    load();
  }, []);

  const saveParams = async () => {
    setError("");
    setSaved("");
    try {
      await api("/api/pending/settings", { method: "POST", json: { params, contact } });
      setSaved("Parametri hugo.toml su dodati u pending.");
      notifyPendingChanged();
    } catch (err) {
      setError(Array.isArray(err.details?.errors) ? err.details.errors.join(" | ") : err.message);
    }
  };

  const saveI18n = async () => {
    setError("");
    setSaved("");
    const byLang = { sr: {}, en: {}, de: {} };
    Object.entries(i18nEdits).forEach(([composite, value]) => {
      const [lang, key] = composite.split("||");
      byLang[lang][key] = value;
    });
    try {
      for (const lang of LANGS) {
        if (Object.keys(byLang[lang]).length) {
          await api("/api/pending/i18n", { method: "POST", json: { lang, updates: byLang[lang] } });
        }
      }
      setSaved("Izmene i18n su dodate u pending.");
      setI18nEdits({});
      notifyPendingChanged();
    } catch (err) {
      setError(err.message);
    }
  };

  const keys = useMemo(() => {
    if (!data?.i18n) return [];
    const set = new Set();
    LANGS.forEach((l) => {
      Object.keys(data.i18n[l]?.keys || {}).forEach((k) => set.add(k));
    });
    return Array.from(set).sort();
  }, [data]);

  const filteredKeys = useMemo(
    () => keys.filter((k) => !i18nSearch || k.toLowerCase().includes(i18nSearch.toLowerCase())),
    [keys, i18nSearch]
  );

  if (error && !data) return <ErrorBox message={error} onRetry={load} />;
  if (!data) return <Loading />;

  const warnings = data.warnings || [];

  return (
    <div>
      <div className="page-head">
        <h1>Postavke</h1>
        <div className="tab-row">
          <button className={`tab ${tab === "params" ? "active" : ""}`} onClick={() => setTab("params")}>hugo.toml</button>
          <button className={`tab ${tab === "i18n" ? "active" : ""}`} onClick={() => setTab("i18n")}>i18n prevodi</button>
        </div>
      </div>

      {error && <div className="panel error-box"><p className="error-text">{error}</p></div>}
      {saved && <div className="success-box">{saved}</div>}

      {warnings.length > 0 && (
        <div className="panel warning-panel">
          {warnings.map((w, i) => <p key={i}>⚠ {w}</p>)}
        </div>
      )}

      {tab === "params" && (
        <div className="panel">
          <h2>[params]</h2>
          <div className="form-grid">
            <label>Opis sajta (params.description)
              <textarea className="text-input" rows={2} value={params.description} onChange={(e) => setParams({ ...params, description: e.target.value })} />
            </label>
            <label>Logo (brandLogo)
              <input className="text-input" value={params.brandLogo} onChange={(e) => setParams({ ...params, brandLogo: e.target.value })} />
            </label>
            <label>OG slika (ogImage)
              <input className="text-input" value={params.ogImage} onChange={(e) => setParams({ ...params, ogImage: e.target.value })} />
            </label>
            <label>Podrazumevana slika (defaultImage)
              <input className="text-input" value={params.defaultImage} onChange={(e) => setParams({ ...params, defaultImage: e.target.value })} />
            </label>
            <label>Google Form za učlanjenje (joinFormUrl)
              <input className="text-input" value={params.joinFormUrl} onChange={(e) => setParams({ ...params, joinFormUrl: e.target.value })} />
            </label>
          </div>

          <h2>[params.contact]</h2>
          <div className="form-grid">
            <label>Email
              <input className="text-input" value={contact.email} onChange={(e) => setContact({ ...contact, email: e.target.value })} />
            </label>
            <label>LinkedIn
              <input className="text-input" value={contact.linkedin} onChange={(e) => setContact({ ...contact, linkedin: e.target.value })} />
            </label>
            <label>Instagram
              <input className="text-input" value={contact.instagram} onChange={(e) => setContact({ ...contact, instagram: e.target.value })} />
            </label>
          </div>
          <div className="button-row">
            <button className="button primary" onClick={saveParams}>Sačuvaj u pending</button>
          </div>
          <p className="hint">
            Menjaju se samo navedeni ključevi — ostatak hugo.toml ([languages], [module.mounts],
            [permalinks]...) ostaje netaknut.
          </p>
        </div>
      )}

      {tab === "i18n" && (
        <div className="panel table-panel">
          <div className="filter-bar">
            <input className="text-input grow" placeholder="Filtriraj ključeve..." value={i18nSearch} onChange={(e) => setI18nSearch(e.target.value)} />
            <button className="button primary" onClick={saveI18n} disabled={!Object.keys(i18nEdits).length}>
              Sačuvaj izmene ({Object.keys(i18nEdits).length})
            </button>
          </div>
          <table className="data-table i18n-table">
            <thead>
              <tr>
                <th>Ključ</th>
                {LANGS.map((l) => <th key={l}>{l}</th>)}
              </tr>
            </thead>
            <tbody>
              {filteredKeys.map((key) => (
                <tr key={key}>
                  <td><code>{key}</code></td>
                  {LANGS.map((l) => {
                    const composite = `${l}||${key}`;
                    const current = Object.prototype.hasOwnProperty.call(i18nEdits, composite)
                      ? i18nEdits[composite]
                      : (data.i18n[l]?.keys?.[key] ?? "");
                    return (
                      <td key={l}>
                        <input
                          className={`text-input ${Object.prototype.hasOwnProperty.call(i18nEdits, composite) ? "edited" : ""}`}
                          value={current}
                          onChange={(e) => setI18nEdits((prev) => ({ ...prev, [composite]: e.target.value }))}
                        />
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          <p className="hint">Komentari i redosled ključeva u YAML fajlovima se čuvaju — menja se samo vrednost.</p>
        </div>
      )}
    </div>
  );
}
