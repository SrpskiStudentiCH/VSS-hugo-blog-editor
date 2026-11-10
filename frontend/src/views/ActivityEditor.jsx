import React, { useEffect, useMemo, useState } from "react";
import { api, imageUrl, notifyPendingChanged } from "../api";
import { ImagePickerModal, Loading } from "../components/Shared";
import MarkdownEditor from "../components/MarkdownEditor";
import slugify from "../utils/slugify";

const LANGS = ["sr", "en", "de"];
const LANG_LABELS = { sr: "Srpski", en: "English", de: "Deutsch" };
const EVENT_TYPE_DEFAULTS = ["social", "hiking", "networking", "assembly", "community"];

function emptyLangState() {
  return {
    title: "",
    description: "",
    semester: "",
    author: "Uredništvo",
    body: "",
  };
}

export default function ActivityEditor({ editing, onDone, onGoPending }) {
  const isNew = !editing?.filename;
  const section = editing?.section || "events";

  const [loading, setLoading] = useState(!isNew);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  // Shared (invariant) fields
  const [shared, setShared] = useState({
    date: new Date().toISOString().slice(0, 10),
    end_date: "",
    event_type: "social",
    draft: false,
    image: "",
    categories: [],
    tags: [],
  });
  const [filename, setFilename] = useState("");
  const [newFilename, setNewFilename] = useState(""); // rename (edit mode)

  // Per-language fields
  const [langs, setLangs] = useState({ sr: emptyLangState(), en: emptyLangState(), de: emptyLangState() });
  const [langTab, setLangTab] = useState("sr");
  const [vocab, setVocab] = useState({ event_types: EVENT_TYPE_DEFAULTS, semesters: { sr: [], en: [], de: [] } });
  const [mediaData, setMediaData] = useState(null);
  const [showPicker, setShowPicker] = useState(false);
  const [translating, setTranslating] = useState("");
  const [warnings, setWarnings] = useState([]);

  useEffect(() => {
    api("/api/activities")
      .then((d) => setVocab(d.vocabulary || vocab))
      .catch(() => {});
    api("/api/media").then(setMediaData).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (isNew) return;
    (async () => {
      setLoading(true);
      setError("");
      try {
        const detail = await api(`/api/activity?section=${encodeURIComponent(section)}&filename=${encodeURIComponent(editing.filename)}`);
        const languages = detail.languages;
        const nextLangs = {};
        LANGS.forEach((l) => {
          const item = languages[l];
          if (!item) {
            nextLangs[l] = emptyLangState();
            return;
          }
          const f = item.front || {};
          nextLangs[l] = {
            title: f.title || "",
            description: f.description || "",
            semester: f.semester || "",
            author: f.author || "Uredništvo",
            body: item.body || "",
          };
        });
        const sr = languages.sr;
        if (sr) {
          const f = sr.front || {};
          setShared({
            date: String(f.date || ""),
            end_date: f.end_date ? String(f.end_date) : "",
            event_type: f.event_type || "",
            draft: !!f.draft,
            image: f.image || "",
            categories: f.categories || [],
            tags: f.tags || [],
          });
        }
        setLangs(nextLangs);
        setFilename(editing.filename);
        setNewFilename("");
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editing]);

  // Auto filename for new events: YYYY-MM-DD-slug.md
  const autoFilename = useMemo(() => {
    const title = langs.sr.title;
    const slug = slugify(title);
    if (!slug) return "";
    if (section === "events") return `${shared.date}-${slug}.md`;
    return `${slug}.md`;
  }, [langs.sr.title, shared.date, section]);

  const updateLang = (lang, key, value) =>
    setLangs((prev) => ({ ...prev, [lang]: { ...prev[lang], [key]: value } }));

  const updateShared = (key, value) => setShared((prev) => ({ ...prev, [key]: value }));

  const listInput = (value) =>
    value
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);

  // ------------------------------------------------------------- translate
  const translateLang = async (target) => {
    const src = langs.sr;
    const texts = [
      src.title,
      src.description,
      section === "events" ? src.semester : "",
      src.body,
    ].map((t) => t || "");
    if (!texts.some((t) => t.trim())) {
      alert("Popuni srpsku verziju pre prevoda.");
      return;
    }
    setTranslating(target);
    setError("");
    try {
      const res = await api("/api/translate", {
        method: "POST",
        json: { texts, target },
      });
      const [title, description, semester, body] = res.translations;
      setLangs((prev) => ({
        ...prev,
        [target]: {
          ...prev[target],
          title: title || "",
          description: description || "",
          semester: section === "events" ? semester || "" : prev[target].semester,
          body: body || "",
        },
      }));
    } catch (err) {
      setError(`Prevod nije uspeo: ${err.message}`);
    } finally {
      setTranslating("");
    }
  };

  // ----------------------------------------------------------------- save
  const save = async () => {
    setError("");
    setWarnings([]);
    const finalFilename = (isNew ? autoFilename : filename).trim();
    const warnings = [];

    const langsToSave = {};
    LANGS.forEach((l) => {
      const st = langs[l];
      if (!st.title.trim() && !st.body.trim() && l !== "sr") return; // skip empty translations
      const front = {
        title: st.title,
        date: shared.date,
        draft: shared.draft,
      };
      if (shared.end_date) front.end_date = shared.end_date;
      if (section === "events") {
        front.event_type = shared.event_type;
        front.semester = st.semester;
      } else {
        front.author = st.author;
      }
      front.description = st.description;
      if (shared.image) front.image = shared.image;
      if (shared.categories.length) front.categories = shared.categories;
      if (shared.tags.length) front.tags = shared.tags;
      langsToSave[l] = { front, body: st.body };
    });

    if (!langsToSave.sr) {
      setError("Srpska verzija mora imati naslov.");
      return;
    }
    LANGS.forEach((l) => {
      if (!langsToSave[l]) warnings.push(`Nedostaje ${l.toUpperCase()} verzija (language switcher neće raditi za nju).`);
    });
    if (section === "events" && !/^\d{4}-\d{2}-\d{2}/.test(finalFilename)) {
      warnings.push("Ime fajla događaja ne počinje datumom (preporuka YYYY-MM-DD-slug.md).");
    }

    try {
      await api("/api/pending/activity", {
        method: "POST",
        json: { section, filename: finalFilename, languages: langsToSave },
      });
      if (!isNew && newFilename && newFilename.trim() && newFilename.trim() !== filename) {
        await api("/api/pending/activity-rename", {
          method: "POST",
          json: { section, filename, new_filename: newFilename.trim() },
        });
      }
      setSaved(true);
      setWarnings(warnings);
      notifyPendingChanged();
    } catch (err) {
      setError(Array.isArray(err.details?.errors) ? err.details.errors.join(" | ") : err.message);
    }
  };

  const publish = async () => {
    // Quick draft toggle used from the editor.
    setShared((prev) => ({ ...prev, draft: !prev.draft }));
  };

  if (loading) return <Loading />;

  const lang = langs[langTab];
  const missingLangs = LANGS.filter((l) => !langs[l].title.trim());

  return (
    <div>
      <div className="page-head">
        <h1>{isNew ? `Nova aktivnost — ${section === "events" ? "događaj" : "blog post"}` : `Izmena: ${filename}`}</h1>
        <div className="button-row">
          <button className="button" onClick={onDone}>← Nazad</button>
          <button className="button primary" onClick={save}>Sačuvaj u pending</button>
          {onGoPending && <button className="button" onClick={onGoPending}>Preview & Commit →</button>}
        </div>
      </div>

      {error && <div className="panel error-box"><p className="error-text">{error}</p></div>}
      {saved && (
        <div className="success-box">
          Izmene su dodate u pending sloj — ništa nije poslato na GitHub dok ne potvrdiš u „Preview & Commit".
        </div>
      )}
      {warnings.length > 0 && (
        <div className="panel warning-panel">
          {warnings.map((w, i) => <p key={i}>⚠ {w}</p>)}
        </div>
      )}

      <div className="two-col">
        {/* Shared fields */}
        <div className="panel">
          <h2>Zajednička polja (sva 3 jezika)</h2>
          <div className="form-grid">
            <label>Datum (YYYY-MM-DD)
              <input className="text-input" type="date" value={shared.date} onChange={(e) => updateShared("date", e.target.value)} />
            </label>
            <label>Kraj (opciono, višednevni)
              <input className="text-input" type="date" value={shared.end_date} onChange={(e) => updateShared("end_date", e.target.value)} />
            </label>
            {section === "events" && (
              <>
                <label>Tip događaja
                  <input
                    className="text-input"
                    list="event-types"
                    value={shared.event_type}
                    onChange={(e) => updateShared("event_type", e.target.value)}
                  />
                  <datalist id="event-types">
                    {vocab.event_types.map((t) => <option key={t} value={t} />)}
                  </datalist>
                </label>
                <label>Semestar (sr)
                  <input
                    className="text-input"
                    list="semesters-sr"
                    value={langs.sr.semester}
                    onChange={(e) => updateLang("sr", "semester", e.target.value)}
                  />
                  <datalist id="semesters-sr">
                    {(vocab.semesters?.sr || []).map((s) => <option key={s} value={s} />)}
                  </datalist>
                </label>
              </>
            )}
            <label>Slika (putanja /images/...)
              <div className="input-with-button">
                <input className="text-input grow" value={shared.image} onChange={(e) => updateShared("image", e.target.value)} />
                <button className="button" onClick={() => setShowPicker(true)}>Galerija</button>
              </div>
              {shared.image && (
                <img
                  className="thumb"
                  src={imageUrl(shared.image.startsWith("/") ? `static${shared.image}` : shared.image)}
                  alt="izabrana"
                  onError={(e) => { e.currentTarget.style.display = "none"; }}
                />
              )}
            </label>
            <label>Kategorije (zarezom)
              <input
                className="text-input"
                list="cats"
                value={shared.categories.join(", ")}
                onChange={(e) => updateShared("categories", listInput(e.target.value))}
              />
              <datalist id="cats">{(vocab.categories || []).map((c) => <option key={c} value={c} />)}</datalist>
            </label>
            <label>Tagovi (zarezom)
              <input
                className="text-input"
                list="tags"
                value={shared.tags.join(", ")}
                onChange={(e) => updateShared("tags", listInput(e.target.value))}
              />
              <datalist id="tags">{(vocab.tags || []).map((t) => <option key={t} value={t} />)}</datalist>
            </label>
            <label className="checkbox-label">
              <input type="checkbox" checked={shared.draft} onChange={publish} />
              Draft (ne objavljuj na sajtu)
            </label>
            <label>Ime fajla
              <input
                className="text-input"
                value={isNew ? autoFilename : filename}
                readOnly={isNew}
                disabled={!isNew}
              />
            </label>
            {!isNew && (
              <label>Preimenuj fajl (opciono — rename u sva 3 jezika u istom commitu)
                <input className="text-input" value={newFilename} onChange={(e) => setNewFilename(e.target.value)} placeholder={filename} />
              </label>
            )}
          </div>
        </div>

        {/* Language editor */}
        <div className="panel">
          <div className="tab-row">
            {LANGS.map((l) => (
              <button key={l} className={`tab ${langTab === l ? "active" : ""}`} onClick={() => setLangTab(l)}>
                {LANG_LABELS[l]}{!langs[l].title.trim() && <span className="warn-inline"> •</span>}
              </button>
            ))}
          </div>

          <div className="form-grid">
            <label>Naslov
              <input className="text-input" value={lang.title} onChange={(e) => updateLang(langTab, "title", e.target.value)} />
            </label>
            <label>Opis
              <textarea className="text-input" rows={2} value={lang.description} onChange={(e) => updateLang(langTab, "description", e.target.value)} />
            </label>
            {section === "events" && langTab !== "sr" && (
              <label>Semestar ({langTab})
                <input
                  className="text-input"
                  list={`semesters-${langTab}`}
                  value={lang.semester}
                  onChange={(e) => updateLang(langTab, "semester", e.target.value)}
                />
                <datalist id={`semesters-${langTab}`}>
                  {(vocab.semesters?.[langTab] || []).map((s) => <option key={s} value={s} />)}
                </datalist>
              </label>
            )}
            {section === "blog" && (
              <label>Autor
                <input className="text-input" value={lang.author} onChange={(e) => updateLang(langTab, "author", e.target.value)} />
              </label>
            )}
          </div>

          {langTab !== "sr" && (
            <div className="button-row">
              <button className="button" disabled={!!translating} onClick={() => translateLang(langTab)}>
                {translating === langTab ? "Prevodim..." : `⚡ Automatski prevedi (${langTab.toUpperCase()})`}
              </button>
              <span className="hint">Prevode se: naslov, opis, semestar i telo. Ime fajla, datum, tip, slika, kategorije i tagovi se NE menjaju.</span>
            </div>
          )}

          <MarkdownEditor
            key={`activity-md-${langTab}`}
            editorId={`activity-md-${langTab}`}
            content={lang.body}
            setContent={(value) => updateLang(langTab, "body", value)}
          />
        </div>
      </div>

      {missingLangs.length > 0 && (
        <p className="hint">⚠ Bez prevoda: {missingLangs.map((l) => LANG_LABELS[l]).join(", ")}</p>
      )}

      {showPicker && mediaData && (
        <ImagePickerModal
          images={mediaData.images}
          onSelect={(path) => {
            updateShared("image", path);
            setShowPicker(false);
          }}
          onClose={() => setShowPicker(false)}
        />
      )}
    </div>
  );
}
