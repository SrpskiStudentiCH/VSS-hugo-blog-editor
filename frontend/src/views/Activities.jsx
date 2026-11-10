import React, { useEffect, useMemo, useState } from "react";
import { api, notifyPendingChanged } from "../api";
import { ConfirmDialog, ErrorBox, Loading } from "../components/Shared";

const LANGS = ["sr", "en", "de"];

export default function Activities({ onEdit, onNew }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [section, setSection] = useState("all");
  const [typeFilter, setTypeFilter] = useState("all");
  const [semesterFilter, setSemesterFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [langFilter, setLangFilter] = useState("all");
  const [confirmDelete, setConfirmDelete] = useState(null); // {entity, mode}

  const load = async () => {
    setError("");
    try {
      const d = await api("/api/activities");
      setData(d);
    } catch (err) {
      setError(err.message);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const filtered = useMemo(() => {
    if (!data) return [];
    const q = search.toLowerCase();
    return data.entities.filter((e) => {
      if (section !== "all" && e.section !== section) return false;
      if (typeFilter !== "all" && e.event_type !== typeFilter) return false;
      if (semesterFilter !== "all" && e.semester !== semesterFilter) return false;
      if (statusFilter === "draft" && !e.draft) return false;
      if (statusFilter === "published" && e.draft) return false;
      if (langFilter !== "all" && !e.languages[langFilter]) return false;
      if (q) {
        const hay = [
          e.filename,
          ...LANGS.map((l) => {
            const m = e.languages[l]?.meta;
            return [m?.title, m?.description, m?.semester].join(" ").toLowerCase();
          }),
        ].join(" ");
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [data, search, section, typeFilter, semesterFilter, statusFilter, langFilter]);

  if (error) return <ErrorBox message={error} onRetry={load} />;
  if (!data) return <Loading />;

  const vocab = data.vocabulary || {};
  const semesters = vocab.semesters?.sr || [];

  const doDelete = async () => {
    if (!confirmDelete) return;
    try {
      await api("/api/pending/activity-delete", {
        method: "POST",
        json: {
          section: confirmDelete.entity.section,
          filename: confirmDelete.entity.filename,
          mode: confirmDelete.mode,
        },
      });
      notifyPendingChanged();
      setConfirmDelete(null);
    } catch (err) {
      alert(err.message);
    }
  };

  return (
    <div>
      <div className="page-head">
        <h1>Aktivnosti</h1>
        <div className="button-row">
          <button className="button primary" onClick={() => onNew("events")}>＋ Novi događaj</button>
          <button className="button" onClick={() => onNew("blog")}>＋ Novi blog post</button>
        </div>
      </div>

      <div className="panel filter-bar">
        <input
          className="text-input grow"
          placeholder="Pretraga (naslov, opis, fajl...)"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select value={section} onChange={(e) => setSection(e.target.value)}>
          <option value="all">Sve sekcije</option>
          <option value="events">Događaji</option>
          <option value="blog">Blog</option>
        </select>
        <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
          <option value="all">Svi tipovi</option>
          {vocab.event_types.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
        <select value={semesterFilter} onChange={(e) => setSemesterFilter(e.target.value)}>
          <option value="all">Svi semestri</option>
          {semesters.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="all">Svi statusi</option>
          <option value="draft">Draft</option>
          <option value="published">Objavljeno</option>
        </select>
        <select value={langFilter} onChange={(e) => setLangFilter(e.target.value)}>
          <option value="all">Svi jezici</option>
          <option value="sr">sr</option>
          <option value="en">en</option>
          <option value="de">de</option>
        </select>
      </div>

      <div className="panel table-panel">
        <table className="data-table">
          <thead>
            <tr>
              <th>Naslov (sr)</th>
              <th>Datum</th>
              <th>Tip</th>
              <th>Semestar</th>
              <th>Status</th>
              <th>Jezici</th>
              <th>Akcije</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((e) => {
              const sr = e.languages.sr?.meta;
              return (
                <tr key={e.section + e.filename}>
                  <td>
                    <div className="cell-title">{sr?.title || "—"}</div>
                    <div className="cell-sub">
                      <code>{e.filename}</code>
                      <span className="section-tag">{e.section}</span>
                    </div>
                  </td>
                  <td>{sr?.date || "—"}</td>
                  <td>{e.event_type || "—"}</td>
                  <td>{e.semester || "—"}</td>
                  <td>
                    {e.draft ? <span className="tag draft">draft</span> : <span className="tag published">objavljeno</span>}
                  </td>
                  <td>
                    <span className="lang-chips">
                      {LANGS.map((l) => (
                        <span key={l} className={`lang-chip ${e.languages[l] ? "" : "missing"}`}>
                          {l}
                        </span>
                      ))}
                    </span>
                    {(e.missing_languages || []).length > 0 && (
                      <span className="warn-inline">⚠ nema {e.missing_languages.join(", ")}</span>
                    )}
                  </td>
                  <td>
                    <div className="button-row compact">
                      <button className="button small" onClick={() => onEdit({ section: e.section, filename: e.filename })}>
                        Izmeni
                      </button>
                      <button
                        className="button small"
                        onClick={() => setConfirmDelete({ entity: e, mode: e.draft ? "delete" : "draft" })}
                        title={e.draft ? "Trajno obriši" : "Postavi kao draft"}
                      >
                        {e.draft ? "Obriši" : "Draft"}
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
            {filtered.length === 0 && (
              <tr><td colSpan={7} className="empty-cell">Nema rezultata.</td></tr>
            )}
          </tbody>
        </table>
        <p className="table-foot">{filtered.length} / {data.entities.length} aktivnosti</p>
      </div>

      {confirmDelete && (
        confirmDelete.mode === "draft" ? (
          <ConfirmDialog
            title="Postavi kao draft?"
            message={`Aktivnost „${confirmDelete.entity.languages.sr?.meta?.title || confirmDelete.entity.filename}" biće sakrivena sa sajta (draft = true u sva 3 jezika). Uvek možeš ponovo objaviti.`}
            confirmText="Postavi kao draft"
            onConfirm={doDelete}
            onCancel={() => setConfirmDelete(null)}
          />
        ) : (
          <ConfirmDialog
            title="Trajno brisanje"
            message={`Ovo briše sva 3 jezička fajla aktivnosti „${confirmDelete.entity.filename}" iz repozitorijuma. Operacija se ne može poništiti kroz alat (ostaje u git istoriji).`}
            confirmText="Trajno obriši"
            confirmWord="OBRIŠI"
            onConfirm={doDelete}
            onCancel={() => setConfirmDelete(null)}
          />
        )
      )}
    </div>
  );
}
