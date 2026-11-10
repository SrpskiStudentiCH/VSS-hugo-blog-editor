import React, { useEffect, useState } from "react";
import { api } from "../api";
import { ErrorBox, Loading } from "../components/Shared";

export default function Dashboard({ onNavigate, onNewActivity }) {
  const [activities, setActivities] = useState(null);
  const [media, setMedia] = useState(null);
  const [pending, setPending] = useState(null);
  const [deploy, setDeploy] = useState(null);
  const [error, setError] = useState("");

  const load = async () => {
    setError("");
    try {
      const [a, m, p, d] = await Promise.all([
        api("/api/activities"),
        api("/api/media"),
        api("/api/pending"),
        api("/api/deploy").catch(() => null),
      ]);
      setActivities(a);
      setMedia(m);
      setPending(p);
      setDeploy(d);
    } catch (err) {
      setError(err.message);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (error) return <ErrorBox message={error} onRetry={load} />;
  if (!activities) return <Loading />;

  const entities = activities.entities || [];
  const events = entities.filter((e) => e.section === "events");
  const blogs = entities.filter((e) => e.section === "blog");
  const drafts = entities.filter((e) => e.draft);
  const missingLangs = entities.filter((e) => (e.missing_languages || []).length > 0);
  const images = media?.images || [];
  const unused = images.filter((img) => (img.referenced_by || []).length === 0);
  const run = deploy?.run;

  const cards = [
    { title: "Aktivnosti", value: entities.length, detail: `${events.length} događaja · ${blogs.length} blog` },
    { title: "Draftovi", value: drafts.length, detail: "nepublikovane aktivnosti" },
    { title: "Nedostajući prevodi", value: missingLangs.length, detail: "aktivnosti bez sva 3 jezika" },
    { title: "Fotografije", value: images.length, detail: `${unused.length} neiskorišćenih` },
    { title: "Pending izmene", value: (pending?.ops || []).length, detail: "čekaju potvrdu" },
    {
      title: "Deploy",
      value: run ? (run.conclusion || run.status || "—") : "—",
      detail: run ? new Date(run.created_at).toLocaleString("sr-RS") : "nema podataka",
    },
  ];

  return (
    <div>
      <h1>Pregled</h1>
      <div className="stat-grid">
        {cards.map((c) => (
          <div key={c.title} className="stat-card">
            <span className="stat-value">{c.value}</span>
            <span className="stat-title">{c.title}</span>
            <span className="stat-detail">{c.detail}</span>
          </div>
        ))}
      </div>

      <div className="panel">
        <h2>Brze akcije</h2>
        <div className="button-row">
          <button className="button primary" onClick={onNewActivity}>＋ Novi događaj</button>
          <button className="button" onClick={() => onNavigate("activities")}>Sve aktivnosti</button>
          <button className="button" onClick={() => onNavigate("media")}>Fotografije</button>
          <button className="button" onClick={() => onNavigate("pending")}>
            Preview & Commit {(pending?.ops || []).length > 0 && `(${pending.ops.length})`}
          </button>
        </div>
      </div>

      {missingLangs.length > 0 && (
        <div className="panel warning-panel">
          <h3>⚠ Aktivnosti sa nedostajućim jezicima</h3>
          <ul>
            {missingLangs.map((e) => (
              <li key={e.section + e.filename}>
                <code>{e.filename}</code> — nema: {e.missing_languages.join(", ")}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
