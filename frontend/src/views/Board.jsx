import React, { useEffect, useState } from "react";
import { api, notifyPendingChanged } from "../api";
import { ErrorBox, ImagePickerModal, Loading } from "../components/Shared";

const LANGS = ["sr", "en", "de"];
const EMPTY_MEMBER = { name: "", role: "", university: "", study: "", email: "", image: "" };

export default function Board() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [members, setMembers] = useState([]); // array of {name, email, image, per:{sr:{role,university,study},...}}
  const [showPicker, setShowPicker] = useState(null); // member name being edited
  const [mediaData, setMediaData] = useState(null);
  const [saved, setSaved] = useState(false);

  const load = () => {
    setError("");
    api("/api/board").then(setData).catch((err) => setError(err.message));
    api("/api/media").then(setMediaData).catch(() => {});
  };

  useEffect(() => {
    load();
  }, []);

  // Build a merged member list (key: name, fallback: index) from the three files.
  useEffect(() => {
    if (!data) return;
    const byName = new Map();
    LANGS.forEach((lang) => {
      const item = data.languages[lang];
      if (!item?.members) return;
      item.members.forEach((m, idx) => {
        const key = m.name || `__${lang}-${idx}`;
        if (!byName.has(key)) {
          byName.set(key, {
            name: m.name || "",
            email: m.email || "",
            image: m.image || "",
            per: { sr: {}, en: {}, de: {} },
          });
        }
        const entry = byName.get(key);
        entry.per[lang] = {
          role: m.role || "",
          university: m.university || "",
          study: m.study || "",
        };
        if (!entry.email && m.email) entry.email = m.email;
        if (!entry.image && m.image) entry.image = m.image;
      });
    });
    setMembers(Array.from(byName.values()));
  }, [data]);

  const update = (index, field, value) =>
    setMembers((prev) => prev.map((m, i) => (i === index ? { ...m, [field]: value } : m)));

  const updatePer = (index, lang, field, value) =>
    setMembers((prev) =>
      prev.map((m, i) =>
        i === index
          ? { ...m, per: { ...m.per, [lang]: { ...(m.per[lang] || {}), [field]: value } } }
          : m
      )
    );

  const move = (index, delta) => {
    setMembers((prev) => {
      const next = [...prev];
      const target = index + delta;
      if (target < 0 || target >= next.length) return prev;
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  };

  const save = async () => {
    setError("");
    setSaved(false);
    const languages = {};
    LANGS.forEach((lang) => {
      languages[lang] = {
        members: members.map((m) => ({
          name: m.name,
          email: m.email,
          image: m.image || "",
          role: m.per[lang]?.role || "",
          university: m.per[lang]?.university || "",
          study: m.per[lang]?.study || "",
        })),
      };
    });
    try {
      await api("/api/pending/board", { method: "POST", json: { languages } });
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
        <h1>Članovi odbora</h1>
        <div className="button-row">
          <button className="button" onClick={() => setMembers((p) => [...p, { ...EMPTY_MEMBER, per: { sr: {}, en: {}, de: {} } }])}>
            ＋ Dodaj člana
          </button>
          <button className="button primary" onClick={save}>Sačuvaj u pending</button>
        </div>
      </div>

      {error && <div className="panel error-box"><p className="error-text">{error}</p></div>}
      {saved && <div className="success-box">Izmene odbora su u pending sloju.</div>}

      <p className="hint">
        Ime, email i slika su zajednički za sva 3 jezika; uloga, univerzitet i smer se unose po jeziku.
        Član bez slike koristi logo kao fallback.
      </p>

      <div className="panel table-panel">
        <table className="data-table board-table">
          <thead>
            <tr>
              <th></th>
              <th>Ime (zajedničko)</th>
              <th>Email</th>
              <th>Slika</th>
              {LANGS.map((l) => (
                <th key={l} colSpan={3}>{l.toUpperCase()} — uloga / univerzitet / smer</th>
              ))}
              <th></th>
            </tr>
          </thead>
          <tbody>
            {members.map((m, i) => (
              <tr key={i}>
                <td className="row-actions">
                  <button className="button tiny" onClick={() => move(i, -1)}>↑</button>
                  <button className="button tiny" onClick={() => move(i, 1)}>↓</button>
                </td>
                <td><input className="text-input" value={m.name} onChange={(e) => update(i, "name", e.target.value)} /></td>
                <td><input className="text-input" value={m.email} onChange={(e) => update(i, "email", e.target.value)} /></td>
                <td>
                  <div className="input-with-button">
                    <input className="text-input" value={m.image || ""} onChange={(e) => update(i, "image", e.target.value)} />
                    <button className="button tiny" onClick={() => setShowPicker(m.name || String(i))}>G</button>
                  </div>
                </td>
                {LANGS.map((l) => (
                  <React.Fragment key={l}>
                    <td><input className="text-input" value={m.per[l]?.role || ""} onChange={(e) => updatePer(i, l, "role", e.target.value)} /></td>
                    <td><input className="text-input" value={m.per[l]?.university || ""} onChange={(e) => updatePer(i, l, "university", e.target.value)} /></td>
                    <td><input className="text-input" value={m.per[l]?.study || ""} onChange={(e) => updatePer(i, l, "study", e.target.value)} /></td>
                  </React.Fragment>
                ))}
                <td>
                  <button className="button small danger" onClick={() => setMembers((p) => p.filter((_, j) => j !== i))}>✕</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {showPicker && mediaData && (
        <ImagePickerModal
          images={mediaData.images.filter((img) => img.path.includes("/board/"))}
          onSelect={(path) => {
            const realIdx = members.findIndex((m, j) => (m.name || String(j)) === showPicker);
            if (realIdx >= 0) update(realIdx, "image", path);
            setShowPicker(null);
          }}
          onClose={() => setShowPicker(null)}
        />
      )}
    </div>
  );
}
