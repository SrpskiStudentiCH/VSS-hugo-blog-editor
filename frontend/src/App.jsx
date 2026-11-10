import React, { useEffect, useState } from "react";
import Login from "./components/Login";
import { api, getToken, onPendingChanged, setToken } from "./api";

import Dashboard from "./views/Dashboard";
import Activities from "./views/Activities";
import ActivityEditor from "./views/ActivityEditor";
import Media from "./views/Media";
import Board from "./views/Board";
import Documents from "./views/Documents";
import Pages from "./views/Pages";
import Settings from "./views/Settings";
import PendingChanges from "./views/PendingChanges";
import History from "./views/History";

const NAV = [
  { key: "dashboard", label: "Pregled", icon: "▦" },
  { key: "activities", label: "Aktivnosti", icon: "☰" },
  { key: "media", label: "Fotografije", icon: "▣" },
  { key: "board", label: "Odbor", icon: "☺" },
  { key: "documents", label: "Dokumenta", icon: "▤" },
  { key: "pages", label: "Stranice", icon: "▥" },
  { key: "settings", label: "Postavke", icon: "⚙" },
  { key: "history", label: "Istorija", icon: "↺" },
  { key: "pending", label: "Preview & Commit", icon: "✓" },
];

function App() {
  const [loggedIn, setLoggedIn] = useState(!!getToken());
  const [view, setView] = useState("dashboard");
  const [editing, setEditing] = useState(null); // {section, filename} | {section, new:true}
  const [pendingCount, setPendingCount] = useState(0);
  const [sidebarOpen, setSidebarOpen] = useState(false); // mobile drawer

  const refreshPending = async () => {
    if (!getToken()) return;
    try {
      const data = await api("/api/pending");
      setPendingCount((data.ops || []).length);
    } catch {
      setPendingCount(0);
    }
  };

  useEffect(() => {
    if (loggedIn) refreshPending();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loggedIn, view]);

  useEffect(() => {
    const off = onPendingChanged(refreshPending);
    return off;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!loggedIn) {
    return (
      <Login
        onLogin={(token) => {
          setToken(token);
          setLoggedIn(true);
        }}
      />
    );
  }

  const openEditor = (entity) => {
    setEditing(entity);
    setView("editor");
    setSidebarOpen(false);
  };

  const navigate = (key) => {
    setView(key);
    setSidebarOpen(false);
  };

  const logout = () => {
    setToken("");
    setLoggedIn(false);
    setSidebarOpen(false);
  };

  const renderView = () => {
    switch (view) {
      case "dashboard":
        return <Dashboard onNavigate={setView} onNewActivity={() => openEditor({ section: "events", filename: null })} />;
      case "activities":
        return (
          <Activities
            onEdit={(e) => openEditor(e)}
            onNew={(section) => openEditor({ section, filename: null })}
          />
        );
      case "editor":
        return <ActivityEditor editing={editing} onDone={() => { setEditing(null); setView("activities"); }} onGoPending={() => setView("pending")} />;
      case "media":
        return <Media />;
      case "board":
        return <Board />;
      case "documents":
        return <Documents />;
      case "pages":
        return <Pages />;
      case "settings":
        return <Settings />;
      case "pending":
        return <PendingChanges />;
      case "history":
        return <History />;
      default:
        return <Dashboard onNavigate={setView} onNewActivity={() => openEditor({ section: "events", filename: null })} />;
    }
  };

  return (
    <div className="admin-shell">
      {sidebarOpen && <div className="sidebar-backdrop" onClick={() => setSidebarOpen(false)} />}
      <aside className={`admin-sidebar ${sidebarOpen ? "open" : ""}`}>
        <button
          className="sidebar-close"
          aria-label="Zatvori meni"
          onClick={() => setSidebarOpen(false)}
        >
          ✕
        </button>
        <div className="admin-brand">
          <strong>VSS Admin</strong>
          <span>Hugo blog editor</span>
        </div>
        <nav>
          {NAV.map((item) => (
            <button
              key={item.key}
              className={view === item.key ? "nav-item active" : "nav-item"}
              onClick={() => navigate(item.key)}
            >
              <span className="nav-icon">{item.icon}</span>
              <span>{item.label}</span>
              {item.key === "pending" && pendingCount > 0 && (
                <span className="badge">{pendingCount}</span>
              )}
            </button>
          ))}
        </nav>
        <button
          className="nav-item primary"
          onClick={() => openEditor({ section: "events", filename: null })}
        >
          <span className="nav-icon">＋</span>
          <span>Nova aktivnost</span>
        </button>
        <div className="admin-sidebar-footer">
          <button className="link-button" onClick={logout}>
            Odjavi se
          </button>
        </div>
      </aside>
      <main className="admin-main">
        <div className="admin-topbar">
          <button
            className="menu-toggle"
            aria-label="Otvori meni"
            onClick={() => setSidebarOpen(true)}
          >
            ☰
          </button>
          <span className="topbar-title">VSS Admin</span>
        </div>
        {renderView()}
      </main>
    </div>
  );
}

export default App;
