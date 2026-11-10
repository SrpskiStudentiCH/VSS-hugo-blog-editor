// Small shared UI components for the admin views.
import React, { useEffect, useMemo, useRef, useState } from "react";
import { imageUrl } from "../api";

export function Loading({ text = "Učitavam..." }) {
  return <div className="panel loading-panel">{text}</div>;
}

export function ErrorBox({ message, onRetry }) {
  return (
    <div className="panel error-box">
      <p className="error-text">{message}</p>
      {onRetry && <button className="button" onClick={onRetry}>Pokušaj ponovo</button>}
    </div>
  );
}

export function SuccessBox({ message }) {
  return <div className="success-box">{message}</div>;
}

// Render a server-computed line diff.
export function DiffView({ ops, maxHeight = 420 }) {
  if (!ops) return null;
  return (
    <div className="diff-view" style={{ maxHeight }}>
      {ops.map((op, i) => (
        <div key={i} className={`diff-line diff-${op.type}`}>
          <span className="diff-sign">
            {op.type === "add" ? "+" : op.type === "del" ? "-" : " "}
          </span>
          <span className="diff-text">{op.text || " "}</span>
        </div>
      ))}
    </div>
  );
}

// Image picker modal: lets the user choose /images/... from the gallery.
export function ImagePickerModal({ images, onSelect, onClose }) {
  const [filter, setFilter] = useState("");
  const filtered = useMemo(
    () =>
      images.filter(
        (img) =>
          !filter ||
          img.path.toLowerCase().includes(filter.toLowerCase())
      ),
    [images, filter]
  );
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>Izaberi sliku</h3>
          <button className="link-button" onClick={onClose}>✕ Zatvori</button>
        </div>
        <input
          className="text-input"
          placeholder="Filtriraj po putanji..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        <div className="picker-grid">
          {filtered.map((img) => (
            <button
              key={img.path}
              className={`picker-item ${img.referenced_by?.length ? "" : "unused"}`}
              title={img.path}
              onClick={() => onSelect(img.path.replace(/^static/, ""))}
            >
              <img src={imageUrl(img.path)} alt={img.path} loading="lazy" />
              <span className="picker-label">{img.path.split("/").pop()}</span>
            </button>
          ))}
          {filtered.length === 0 && <p>Nema rezultata.</p>}
        </div>
      </div>
    </div>
  );
}

// Confirm dialog with a required typed confirmation for dangerous actions.
export function ConfirmDialog({ title, message, confirmText, confirmWord, onConfirm, onCancel }) {
  const [typed, setTyped] = useState("");
  const inputRef = useRef(null);
  useEffect(() => {
    if (confirmWord && inputRef.current) inputRef.current.focus();
  }, [confirmWord]);
  const ok = !confirmWord || typed.trim() === confirmWord;
  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>{title}</h3>
        <p className="modal-message">{message}</p>
        {confirmWord && (
          <input
            ref={inputRef}
            className="text-input"
            placeholder={`Ukucaj: ${confirmWord}`}
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
          />
        )}
        <div className="button-row">
          <button className="button danger" disabled={!ok} onClick={onConfirm}>
            {confirmText || "Potvrdi"}
          </button>
          <button className="button" onClick={onCancel}>Otkaži</button>
        </div>
      </div>
    </div>
  );
}
