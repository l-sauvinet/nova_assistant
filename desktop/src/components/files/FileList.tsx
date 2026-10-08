import { useRef, useState, type KeyboardEvent } from "react";
import { Lock } from "lucide-react";
import type { FileEntry, NovaApi } from "../../lib/api";
import { formatDate, iconFor, PREVIEWABLE_IMAGES, typeLabel } from "../../lib/paths";
import { formatSize } from "../MediaView";

type FileListProps = {
  api: NovaApi;
  entries: FileEntry[];
  view: "grid" | "list";
  selectedPath: string | null;
  showLocation?: boolean;
  onSelect: (entry: FileEntry) => void;
  onActivate: (entry: FileEntry) => void;
  renamingPath: string | null;
  onStartRename: (entry: FileEntry) => void;
  onRename: (entry: FileEntry, name: string) => Promise<void>;
  onCancelRename: () => void;
};

type RenameInputProps = {
  entry: FileEntry;
  className: string;
  onRename: (entry: FileEntry, name: string) => Promise<void>;
  onCancel: () => void;
};

const selectBaseName = (input: HTMLInputElement, entry: FileEntry) => {
  const dot = entry.is_dir ? -1 : entry.name.lastIndexOf(".");
  input.setSelectionRange(0, dot > 0 ? dot : entry.name.length);
};

const RenameInput = ({ entry, className, onRename, onCancel }: RenameInputProps) => {
  const [value, setValue] = useState(entry.name);
  const settled = useRef(false);

  const commit = async () => {
    if (settled.current) return;
    settled.current = true;
    const name = value.trim();
    if (!name || name === entry.name) return onCancel();
    try {
      await onRename(entry, name);
    } catch {
      settled.current = false;
    }
  };

  return (
    <input
      className={className}
      aria-label={`Nouveau nom pour ${entry.name}`}
      autoFocus
      value={value}
      onChange={(event) => setValue(event.target.value)}
      onFocus={(event) => selectBaseName(event.target, entry)}
      onClick={(event) => event.stopPropagation()}
      onDoubleClick={(event) => event.stopPropagation()}
      onKeyDown={(event) => {
        event.stopPropagation();
        if (event.key === "Enter") commit();
        if (event.key === "Escape") {
          settled.current = true;
          onCancel();
        }
      }}
      onBlur={commit}
    />
  );
};

const Thumbnail = ({ api, entry }: { api: NovaApi; entry: FileEntry }) => {
  const Icon = iconFor(entry);
  if (PREVIEWABLE_IMAGES.includes(entry.extension)) {
    return <img className="file-thumbnail" src={api.thumbnailUrl(entry.path)} alt="" loading="lazy" />;
  }
  return (
    <>
      <Icon className={`file-icon ${entry.is_dir ? "file-icon-folder" : ""}`} size={entry.is_dir ? 44 : 38} strokeWidth={1.4} aria-hidden="true" />
      {!entry.readable && <Lock className="file-lock" size={16} aria-label="Accès refusé" />}
    </>
  );
};

const parentOf = (entry: FileEntry) => entry.path.slice(0, Math.max(0, entry.path.length - entry.name.length - 1));

export const FileList = ({
  api, entries, view, selectedPath, showLocation = false, onSelect, onActivate, renamingPath, onStartRename, onRename, onCancelRename,
}: FileListProps) => {
  const handleKey = (event: KeyboardEvent, entry: FileEntry) => {
    if (event.key === "Enter") onActivate(entry);
    if (event.key === "F2") {
      event.preventDefault();
      onStartRename(entry);
    }
  };

  if (entries.length === 0) {
    return <p className="files-empty">Rien à afficher ici.</p>;
  }
  if (view === "grid") {
    return (
      <ul className="file-grid" aria-label="Fichiers">
        {entries.map((entry) => (
          <li key={entry.path}>
            {entry.path === renamingPath ? (
              <div className="file-tile selected renaming">
                <span className="file-tile-visual"><Thumbnail api={api} entry={entry} /></span>
                <RenameInput entry={entry} className="file-rename-input" onRename={onRename} onCancel={onCancelRename} />
              </div>
            ) : (
            <button
              type="button"
              className={`file-tile ${entry.path === selectedPath ? "selected" : ""} ${entry.hidden ? "is-hidden" : ""} ${entry.readable ? "" : "is-locked"}`}
              onClick={() => onSelect(entry)}
              onDoubleClick={() => onActivate(entry)}
              onKeyDown={(event) => handleKey(event, entry)}
              aria-pressed={entry.path === selectedPath}
              title={entry.readable ? (showLocation ? entry.path : entry.name) : `${entry.name} — accès refusé par Windows`}
            >
              <span className="file-tile-visual"><Thumbnail api={api} entry={entry} /></span>
              <span className="file-tile-name">{entry.name}</span>
            </button>
            )}
          </li>
        ))}
      </ul>
    );
  }
  return (
    <table className="file-table">
      <thead>
        <tr>
          <th>Nom</th>
          {showLocation && <th>Emplacement</th>}
          <th>Modifié</th>
          <th>Type</th>
          <th className="numeric">Taille</th>
        </tr>
      </thead>
      <tbody>
        {entries.map((entry) => {
          const Icon = iconFor(entry);
          return (
            <tr
              key={entry.path}
              className={`${entry.path === selectedPath ? "selected" : ""} ${entry.hidden ? "is-hidden" : ""} ${entry.readable ? "" : "is-locked"}`}
              onClick={() => onSelect(entry)}
              onDoubleClick={() => onActivate(entry)}
              onKeyDown={(event) => handleKey(event, entry)}
              tabIndex={0}
              aria-selected={entry.path === selectedPath}
            >
              <td className="file-name-cell">
                {entry.readable ? (
                  <Icon className={`file-icon ${entry.is_dir ? "file-icon-folder" : ""}`} size={18} strokeWidth={1.6} aria-hidden="true" />
                ) : (
                  <Lock className="file-icon" size={18} strokeWidth={1.6} aria-label="Accès refusé" />
                )}
                {entry.path === renamingPath ? (
                  <RenameInput entry={entry} className="file-rename-input" onRename={onRename} onCancel={onCancelRename} />
                ) : (
                  <span>{entry.name}</span>
                )}
              </td>
              {showLocation && <td className="muted file-location">{parentOf(entry)}</td>}
              <td className="muted">{formatDate(entry.modified)}</td>
              <td className="muted">{typeLabel(entry)}</td>
              <td className="muted numeric">{entry.size === null ? "—" : formatSize(entry.size)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
};
