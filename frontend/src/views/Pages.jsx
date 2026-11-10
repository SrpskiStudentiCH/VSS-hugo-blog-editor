import React, { useEffect, useMemo, useState } from "react";
import { api, notifyPendingChanged } from "../api";
import MarkdownEditor from "../components/MarkdownEditor";
import { ErrorBox, ImagePickerModal, Loading } from "../components/Shared";

const LANGS = ["sr", "en", "de"];
const LANG_LABELS = { sr: "Srpski", en: "English", de: "Deutsch" };

const SECTIONS = [
  { key: "about", label: "O nama" },
  { key: "alumni", label: "Alumni" },
  { key: "support", label: "Podrška" },
  { key: "join", label: "Postani član" },
  { key: "contact", label: "Kontakt" },
  { key: "media", label: "Mediji" },
];

// Field definitions per section (front matter).
const SECTION_FIELDS = {
  about: {
    strings: ["statement", "who_title", "who_text", "founded", "image"],
    arrays: { what: ["title", "text"], values: [] }, // values: [] => plain string list
  },
  alumni: {
    strings: ["statement", "quote", "image", "vsas_url"],
    arrays: { highlights: ["title", "text"] },
  },
  support: {
    strings: ["image"],
    arrays: { ways: ["kind", "title", "text", "cta", "url"] },
  },
  join: { strings: ["title", "description", "image"], arrays: {} },
  contact: { strings: ["title", "description", "image"], arrays: {} },
  media: { strings: ["title", "description", "image"], arrays: {} },
};

function emptyFront(section) {
  const def = SECTION_FIELDS[section] || { strings: [], arrays: {} };
  const front = {};
  def.strings.forEach((k) => (front[k] = ""));
  Object.entries(def.arrays).forEach(([k, fields]) => (front[k] = []));
  return front;
}

export default function Pages() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [section, setSection] = useState("about");
  const [guideFile, setGuideFile] = useState("");
  const [langTab, setLangTab] = useState("sr");
  const [state, setState] = useState({}); // lang -> {front, body}
  const [saved, setSaved] = useState(false);
  const [mediaData, setMediaData] = useState(null);
  const [showPicker, setShowPicker] = useState(null); // field key

  const load = () => {
    setError("");
    api("/api/pages").then(setData).catch((err) => setError(err.message));
    api("/api/media").then(setMediaData).catch(() => {});
  };

  useEffect(() => {
    load();
  }, []);

  const guideFiles = useMemo(
    () => (data?.guide ? Object.keys(data.guide).sort() : []),
    [data]
  );

  // Load the selected section into editable state.
  useEffect(() => {
    if (!data) return;
    if (section === "guide") {
      if (!guideFile) return;
      const item = data.guide[guideFile];
      const next = {};
      LANGS.forEach((l) => {
        const langItem = item?.languages?.[l];
        next[l] = {
          front: langItem ? { ...langItem.front } : { title: "", description: "", toc: false, image: "" },
          body: langItem?.body || "",
        };
      });
      setState(next);
      return;
    }
    const page = data.pages?.[section];
    const next = {};
    LANGS.forEach((l) => {
      const langItem = page?.[l];
      next[l] = {
        front: langItem ? { ...langItem.front } : emptyFront(section),
        body: langItem?.body || "",
      };
    });
    setState(next);
  }, [data, section, guideFile]);

  const updateFront = (lang, key, value) =>
    setState((prev) => ({ ...prev, [lang]: { ...prev[lang], front: { ...prev[lang].front, [key]: value } } }));

  const updateArrayItem = (lang, key, index, field, value) =>
    setState((prev) => {
      const arr = [...(prev[lang].front[key] || [])];
      if (field === null) {
        arr[index] = value;
      } else {
        arr[index] = { ...arr[index], [field]: value };
      }
      return { ...prev, [lang]: { ...prev[lang], front: { ...prev[lang].front, [key]: arr } } };
    });

  const addArrayItem = (lang, key, fields) => {
    const item = fields.length ? Object.fromEntries(fields.map((f) => [f, ""])) : "";
    setState((prev) => ({
      ...prev,
      [lang]: { ...prev[lang], front: { ...prev[lang].front, [key]: [...(prev[lang].front[key] || []), item] } },
    }));
  };

  const removeArrayItem = (lang, key, index) =>
    setState((prev) => ({
      ...prev,
      [lang]: {
        ...prev[lang],
        front: { ...prev[lang].front, [key]: (prev[lang].front[key] || []).filter((_, i) => i !== index) },
      },
    }));

  const save = async () => {
    setError("");
    setSaved(false);
    const languages = {};
    LANGS.forEach((l) => {
      if (!state[l]) return;
      languages[l] = { front: state[l].front, body: state[l].body };
    });
    const payload = { section, languages };
    if (section === "guide") payload.filename = guideFile;
    try {
      await api("/api/pending/page", { method: "POST", json: payload });
      setSaved(true);
      notifyPendingChanged();
    } catch (err) {
      setError(Array.isArray(err.details?.errors) ? err.details.errors.join(" | ") : err.message);
    }
  };

  if (error && !data) return <ErrorBox message={error} onRetry={load} />;
  if (!data) return <Loading />;

  const isGuide = section === "guide";
  const def = isGuide
    ? { strings: ["title", "description", "toc", "image"], arrays: {} }
    : SECTION_FIELDS[section];
  const lang = state[langTab] || { front: {}, body: "" };

  return (
    <div>
      <div className="page-head">
        <h1>Stranice</h1>
        <div className="button-row">
          <button className="button" onClick={() => setSection("guide")}>Vodič (guide)</button>
          <button className="button primary" onClick={save}>Sačuvaj u pending</button>
        </div>
      </div>

      <div className="panel filter-bar">
        {SECTIONS.map((s) => (
          <button key={s.key} className={`tab ${section === s.key ? "active" : ""}`} onClick={() => setSection(s.key)}>
            {s.label}
          </button>
        ))}
        {isGuide && (
          <select value={guideFile} onChange={(e) => setGuideFile(e.target.value)}>
            <option value="">Izaberi stranicu vodiča...</option>
            {guideFiles.map((f) => <option key={f} value={f}>{f}</option>)}
          </select>
        )}
      </div>

      {error && <div className="panel error-box"><p className="error-text">{error}</p></div>}
      {saved && <div className="success-box">Izmene stranice su u pending sloju.</div>}

      {(!isGuide || guideFile) && (
        <>
          <div className="tab-row">
            {LANGS.map((l) => (
              <button key={l} className={`tab ${langTab === l ? "active" : ""}`} onClick={() => setLangTab(l)}>
                {LANG_LABELS[l]}
              </button>
            ))}
          </div>

          <div className="two-col">
            <div className="panel">
              <h2>Front matter ({langTab})</h2>
              <div className="form-grid">
                {def.strings.map((key) => (
                  <label key={key}>
                    {key}
                    {key === "toc" ? (
                      <select className="text-input" value={lang.front[key] ? "true" : "false"} onChange={(e) => updateFront(langTab, key, e.target.value === "true")}>
                        <option value="false">false</option>
                        <option value="true">true</option>
                      </select>
                    ) : key === "image" ? (
                      <div className="input-with-button">
                        <input className="text-input grow" value={lang.front[key] || ""} onChange={(e) => updateFront(langTab, key, e.target.value)} />
                        <button className="button tiny" onClick={() => setShowPicker(key)}>G</button>
                      </div>
                    ) : (
                      <textarea className="text-input" rows={2} value={lang.front[key] || ""} onChange={(e) => updateFront(langTab, key, e.target.value)} />
                    )}
                  </label>
                ))}

                {Object.entries(def.arrays).map(([key, fields]) => (
                  <div key={key} className="array-editor">
                    <div className="array-head">
                      <strong>{key}[]</strong>
                      <button className="button tiny" onClick={() => addArrayItem(langTab, key, fields)}>＋ Dodaj stavku</button>
                    </div>
                    {(lang.front[key] || []).map((item, i) => (
                      <div key={i} className="array-item">
                        {fields.length === 0 ? (
                          <div className="input-with-button">
                            <input className="text-input grow" value={item || ""} onChange={(e) => updateArrayItem(langTab, key, i, null, e.target.value)} />
                            <button className="button tiny danger" onClick={() => removeArrayItem(langTab, key, i)}>✕</button>
                          </div>
                        ) : (
                          <div className="array-item-grid">
                            {fields.map((f) => (
                              <label key={f}>{f}
                                <input className="text-input" value={item[f] || ""} onChange={(e) => updateArrayItem(langTab, key, i, f, e.target.value)} />
                              </label>
                            ))}
                            <button className="button tiny danger" onClick={() => removeArrayItem(langTab, key, i)}>✕</button>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            </div>

            <div className="panel">
              <MarkdownEditor
                key={`page-md-${langTab}`}
                editorId={`page-md-${langTab}`}
                content={lang.body}
                setContent={(value) => setState((prev) => ({ ...prev, [langTab]: { ...prev[langTab], body: value } }))}
              />
            </div>
          </div>
        </>
      )}

      {showPicker && mediaData && (
        <ImagePickerModal
          images={mediaData.images}
          onSelect={(path) => {
            updateFront(langTab, showPicker, path);
            setShowPicker(null);
          }}
          onClose={() => setShowPicker(null)}
        />
      )}
    </div>
  );
}
