import {
  ArrowLeft, ArrowRight, ArrowUp, ChevronRight, Download, Eye, EyeOff, FolderPlus, HardDrive, House, Image, LayoutGrid, List,
  PanelRight, PanelRightClose,
  Monitor, Music, RefreshCw, Search, Sparkles, Terminal, Upload, Video, FileText, X, type LucideIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import type { FileEntry, FolderListing, NovaApi, Place } from "../../lib/api";
import type { MediaActions } from "../../lib/mediaActions";
import { breadcrumbs } from "../../lib/paths";
import { openWithCheck } from "../../lib/safeOpen";
import { FileList } from "./FileList";
import { FilePreviewPanel } from "./FilePreviewPanel";

type FilesScreenProps = {
  api: NovaApi;
  mediaActions: MediaActions;
  onAskNova: (entry: FileEntry) => void;
};

type SearchResults = { query: string; entries: FileEntry[]; truncated: boolean };

const PLACE_ICONS: Record<string, LucideIcon> = {
  home: House, desktop: Monitor, documents: FileText, downloads: Download, pictures: Image, music: Music,
  videos: Video, drive: HardDrive, system: Terminal, nova: Sparkles,
};

const VIEW_KEY = "nova.files.view";
const HIDDEN_KEY = "nova.files.hidden";
const PREVIEW_KEY = "nova.files.preview";

const readPreference = (key: string, fallback: string) => {
  try {
    return window.localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
};

const writePreference = (key: string, value: string) => {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* preferences are optional */
  }
};

export const FilesScreen = ({ api, mediaActions, onAskNova }: FilesScreenProps) => {
  const [places, setPlaces] = useState<Place[]>([]);
  const [listing, setListing] = useState<FolderListing | null>(null);
  const [history, setHistory] = useState<{ stack: string[]; index: number }>({ stack: [], index: -1 });
  const [selected, setSelected] = useState<FileEntry | null>(null);
  const [view, setView] = useState<"grid" | "list">(() => (readPreference(VIEW_KEY, "grid") === "list" ? "list" : "grid"));
  const [showHidden, setShowHidden] = useState(() => readPreference(HIDDEN_KEY, "false") === "true");
  const [showPreview, setShowPreview] = useState(() => readPreference(PREVIEW_KEY, "true") === "true");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResults | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [newFolder, setNewFolder] = useState<string | null>(null);
  const [renamingPath, setRenamingPath] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const uploadInput = useRef<HTMLInputElement>(null);

  const currentPath = history.stack[history.index] ?? null;

  const loadedPath = useRef<string | null>(null);

  const load = useCallback(
    async (path: string) => {
      setLoading(true);
      setError(null);
      try {
        setListing(await api.listFolder(path));
        loadedPath.current = path;
        return true;
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : String(reason));
        return false;
      } finally {
        setLoading(false);
      }
    },
    [api],
  );

  const navigate = useCallback(
    async (path: string) => {
      if (!(await load(path))) return;
      setResults(null);
      setQuery("");
      setSelected(null);
      setRenamingPath(null);
      setHistory((current) => ({ stack: [...current.stack.slice(0, current.index + 1), path], index: current.index + 1 }));
    },
    [load],
  );

  useEffect(() => {
    api.places().then(
      ({ places: found }) => {
        setPlaces(found);
        if (found.length) navigate(found[0].path);
      },
      (reason: Error) => setError(reason.message),
    );
  }, [api, navigate]);

  useEffect(() => {
    if (currentPath && currentPath !== loadedPath.current) load(currentPath);
  }, [currentPath, load]);

  const move = (offset: number) => {
    setResults(null);
    setSelected(null);
    setRenamingPath(null);
    setHistory((current) => ({ ...current, index: Math.min(Math.max(current.index + offset, 0), current.stack.length - 1) }));
  };

  const activate = (entry: FileEntry) => {
    if (entry.is_dir && !entry.readable) {
      setSelected(entry);
      return;
    }
    if (entry.is_dir) navigate(entry.path);
    else openWithCheck((confirmed) => api.openFile(entry.path, confirmed)).catch((reason: Error) => setError(reason.message));
  };

  const search = async () => {
    if (!currentPath || !query.trim()) return setResults(null);
    setLoading(true);
    setError(null);
    try {
      const found = await api.searchFiles(currentPath, query);
      setResults({ query: found.query, entries: found.entries, truncated: found.truncated });
      setSelected(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setLoading(false);
    }
  };

  const uploadFiles = async (files: File[]) => {
    if (!currentPath) return;
    setError(null);
    try {
      for (const file of files) await api.uploadInto(currentPath, file);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
    load(currentPath);
  };

  const createFolder = async () => {
    if (!currentPath || !newFolder?.trim()) return setNewFolder(null);
    try {
      await api.createFolder(currentPath, newFolder.trim());
      setNewFolder(null);
      load(currentPath);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  };

  const startRename = (entry: FileEntry) => {
    setSelected(entry);
    setRenamingPath(entry.path);
  };

  const rename = async (entry: FileEntry, name: string) => {
    setError(null);
    try {
      const { entry: renamed } = await api.renameFile(entry.path, name);
      setRenamingPath(null);
      setSelected(renamed);
      if (results) setResults({ ...results, entries: results.entries.map((item) => (item.path === entry.path ? renamed : item)) });
      if (currentPath) load(currentPath);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      throw reason;
    }
  };

  const trash = async (entry: FileEntry) => {
    await api.trashFile(entry.path);
    setSelected(null);
    if (currentPath) load(currentPath);
  };

  const toggleView = () => {
    const next = view === "grid" ? "list" : "grid";
    setView(next);
    writePreference(VIEW_KEY, next);
  };

  const togglePreview = () => {
    setShowPreview(!showPreview);
    writePreference(PREVIEW_KEY, String(!showPreview));
  };

  const toggleHidden = () => {
    setShowHidden(!showHidden);
    writePreference(HIDDEN_KEY, String(!showHidden));
  };

  const handleDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    if (event.dataTransfer.files.length) uploadFiles(Array.from(event.dataTransfer.files));
  };

  const shownEntries = useMemo(() => {
    const entries = results ? results.entries : listing?.entries ?? [];
    return showHidden ? entries : entries.filter((entry) => !entry.hidden && entry.readable);
  }, [results, listing, showHidden]);

  const groupedPlaces = useMemo(() => {
    const groups = new Map<string, Place[]>();
    for (const place of places) groups.set(place.group, [...(groups.get(place.group) ?? []), place]);
    return [...groups.entries()];
  }, [places]);

  return (
    <div className="files-screen">
      <aside className="places" aria-label="Emplacements">
        {groupedPlaces.map(([group, items]) => (
          <section key={group}>
            <h3 className="conversation-group">{group}</h3>
            <ul>
              {items.map((place) => {
                const Icon = PLACE_ICONS[place.icon] ?? HardDrive;
                const active = currentPath === place.path;
                return (
                  <li key={place.path}>
                    <button className={`place ${active ? "active" : ""}`} onClick={() => navigate(place.path)} title={place.path}>
                      <Icon size={16} aria-hidden="true" /> <span>{place.label}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
      </aside>

      <section
        className="files-main"
        onDragOver={(event) => {
          if (!Array.from(event.dataTransfer.types).includes("Files")) return;
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={(event) => event.currentTarget === event.target && setDragging(false)}
        onDrop={handleDrop}
      >
        {dragging && (
          <div className="drop-overlay">
            <Upload size={34} aria-hidden="true" />
            <p>Déposer dans « {listing?.name} »</p>
          </div>
        )}
        <div className="files-toolbar">
          <div className="toolbar-group">
            <button className="icon-button" onClick={() => move(-1)} disabled={history.index <= 0} aria-label="Précédent" title="Précédent"><ArrowLeft size={17} /></button>
            <button className="icon-button" onClick={() => move(1)} disabled={history.index >= history.stack.length - 1} aria-label="Suivant" title="Suivant"><ArrowRight size={17} /></button>
            <button className="icon-button" onClick={() => listing?.parent && navigate(listing.parent)} disabled={!listing?.parent} aria-label="Dossier parent" title="Dossier parent"><ArrowUp size={17} /></button>
            <button className="icon-button" onClick={() => currentPath && load(currentPath)} aria-label="Actualiser" title="Actualiser"><RefreshCw size={16} className={loading ? "spin" : ""} /></button>
          </div>
          <nav className="breadcrumb" aria-label="Chemin">
            {currentPath &&
              breadcrumbs(currentPath).map((crumb, index, all) => (
                <span key={crumb.path} className="crumb">
                  <button onClick={() => navigate(crumb.path)} aria-current={index === all.length - 1 ? "page" : undefined}>{crumb.label}</button>
                  {index < all.length - 1 && <ChevronRight size={14} aria-hidden="true" />}
                </span>
              ))}
          </nav>
          <form className="files-search" onSubmit={(event) => { event.preventDefault(); search(); }}>
            <Search size={15} aria-hidden="true" />
            <input aria-label="Rechercher dans ce dossier" placeholder="Rechercher ici…" value={query} onChange={(event) => setQuery(event.target.value)} />
            {results && (
              <button type="button" className="icon-button small" onClick={() => { setResults(null); setQuery(""); }} aria-label="Effacer la recherche"><X size={14} /></button>
            )}
          </form>
          <div className="toolbar-group">
            <button className="icon-button" onClick={() => setNewFolder("Nouveau dossier")} aria-label="Nouveau dossier" title="Nouveau dossier"><FolderPlus size={17} /></button>
            <button className="icon-button" onClick={() => uploadInput.current?.click()} aria-label="Ajouter des fichiers ici" title="Ajouter des fichiers ici"><Upload size={17} /></button>
            <button className="icon-button" onClick={togglePreview} aria-label={showPreview ? "Masquer le volet d'aperçu" : "Afficher le volet d'aperçu"} title={showPreview ? "Masquer le volet d'aperçu" : "Afficher le volet d'aperçu"}>
              {showPreview ? <PanelRightClose size={17} /> : <PanelRight size={17} />}
            </button>
            <button className="icon-button" onClick={toggleHidden} aria-label={showHidden ? "Masquer les fichiers cachés" : "Afficher les fichiers cachés"} title={showHidden ? "Masquer les fichiers cachés" : "Afficher les fichiers cachés"}>
              {showHidden ? <Eye size={17} /> : <EyeOff size={17} />}
            </button>
            <button className="icon-button" onClick={toggleView} aria-label={view === "grid" ? "Affichage en liste" : "Affichage en grille"} title={view === "grid" ? "Affichage en liste" : "Affichage en grille"}>
              {view === "grid" ? <List size={17} /> : <LayoutGrid size={17} />}
            </button>
            <input ref={uploadInput} type="file" multiple hidden onChange={(event) => { if (event.target.files) uploadFiles(Array.from(event.target.files)); event.target.value = ""; }} />
          </div>
        </div>

        {newFolder !== null && (
          <form className="files-inline-form" onSubmit={(event) => { event.preventDefault(); createFolder(); }}>
            <FolderPlus size={16} aria-hidden="true" />
            <input aria-label="Nom du nouveau dossier" autoFocus value={newFolder} onChange={(event) => setNewFolder(event.target.value)} onFocus={(event) => event.target.select()} onKeyDown={(event) => event.key === "Escape" && setNewFolder(null)} />
            <button type="submit" className="button-primary">Créer</button>
            <button type="button" className="button-secondary" onClick={() => setNewFolder(null)}>Annuler</button>
          </form>
        )}
        {error && <div className="files-error" role="alert">{error}</div>}
        {results && (
          <p className="files-results-info muted">
            {results.entries.length} résultat{results.entries.length > 1 ? "s" : ""} pour « {results.query} »{results.truncated ? " (recherche interrompue, précise ta recherche)" : ""}
          </p>
        )}

        <div className="files-content">
          <FileList
            api={api}
            entries={shownEntries}
            view={view}
            selectedPath={selected?.path ?? null}
            showLocation={results !== null}
            onSelect={setSelected}
            onActivate={activate}
            renamingPath={renamingPath}
            onStartRename={startRename}
            onRename={rename}
            onCancelRename={() => setRenamingPath(null)}
          />
        </div>
      </section>

      {showPreview && !selected && (
        <aside className="preview-panel preview-empty" aria-label="Aperçu">
          <p className="muted">Sélectionne un fichier ou un dossier pour voir son aperçu.</p>
        </aside>
      )}
      {showPreview && selected && (
        <FilePreviewPanel
          api={api}
          mediaActions={mediaActions}
          entry={selected}
          onClose={() => setSelected(null)}
          onOpenFolder={navigate}
          onAskNova={onAskNova}
          onStartRename={startRename}
          onTrash={trash}
        />
      )}
    </div>
  );
};
