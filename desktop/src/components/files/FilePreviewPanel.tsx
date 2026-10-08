import { Download, ExternalLink, KeyRound, Pencil, Sparkles, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";
import type { FileEntry, NovaApi } from "../../lib/api";
import type { MediaActions } from "../../lib/mediaActions";
import { formatDate, iconFor, PREVIEWABLE_IMAGES, PREVIEWABLE_TEXT, typeLabel } from "../../lib/paths";
import { openWithCheck } from "../../lib/safeOpen";
import type { MediaItem } from "../../lib/useChat";
import { formatSize } from "../MediaView";

type FilePreviewPanelProps = {
  api: NovaApi;
  mediaActions: MediaActions;
  entry: FileEntry;
  onClose: () => void;
  onOpenFolder: (path: string) => void;
  onAskNova: (entry: FileEntry) => void;
  onStartRename: (entry: FileEntry) => void;
  onTrash: (entry: FileEntry) => Promise<void>;
};

const MAX_TEXT_PREVIEW = 20_000;
const MAX_TEXT_FILE_BYTES = 2_000_000;

const Visual = ({ entry, url, text }: { entry: FileEntry; url: string | null; text: string | null }) => {
  const Icon = iconFor(entry);
  if (text !== null) return <pre className="preview-text">{text}</pre>;
  if (url && PREVIEWABLE_IMAGES.includes(entry.extension)) return <img src={url} alt={entry.name} />;
  if (url && entry.extension === "svg") return <img src={url} alt={entry.name} className="preview-svg" />;
  if (url && entry.extension === "pdf") return <iframe title={entry.name} src={url} />;
  if (url && ["html", "htm"].includes(entry.extension)) return <iframe title={entry.name} src={url} sandbox="allow-scripts" />;
  return <Icon size={72} strokeWidth={1.2} className={`file-icon ${entry.is_dir ? "file-icon-folder" : ""}`} aria-hidden="true" />;
};

export const FilePreviewPanel = ({ api, mediaActions, entry, onClose, onOpenFolder, onAskNova, onStartRename, onTrash }: FilePreviewPanelProps) => {
  const [media, setMedia] = useState<MediaItem | null>(null);
  const [text, setText] = useState<string | null>(null);
  const [confirmTrash, setConfirmTrash] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [unlocking, setUnlocking] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setMedia(null);
    setText(null);
    setConfirmTrash(false);
    setMessage(null);
    if (entry.is_dir) return;
    const wantsText = PREVIEWABLE_TEXT.includes(entry.extension) && (entry.size ?? 0) < MAX_TEXT_FILE_BYTES;
    api.previewFile(entry.path).then(
      async ({ media: registered }) => {
        if (cancelled) return;
        setMedia(registered);
        if (wantsText) {
          const content = await fetch(`${api.baseUrl}${registered.url}`).then((response) => response.text());
          if (!cancelled) setText(content.slice(0, MAX_TEXT_PREVIEW));
        }
      },
      (reason: Error) => {
        if (!cancelled) setMessage(reason.message);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [api, entry]);

  const run = async (action: () => Promise<unknown>) => {
    setMessage(null);
    try {
      await action();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : String(reason));
    }
  };

  const unlock = async () => {
    setUnlocking(true);
    await run(async () => {
      await api.requestAccess(entry.path);
      onOpenFolder(entry.path);
    });
    setUnlocking(false);
  };

  const download = () =>
    run(async () => {
      if (!media) return;
      const saved = await mediaActions.download(media);
      if (saved) setMessage(`Enregistré : ${saved}`);
    });

  return (
    <aside className="preview-panel" aria-label={`Aperçu de ${entry.name}`}>
      <div className="preview-header">
        <span className="preview-title" title={entry.name}>{entry.name}</span>
        <button className="icon-button small" onClick={onClose} aria-label="Fermer l'aperçu"><X size={16} /></button>
      </div>
      <div className="preview-visual">
        <Visual entry={entry} url={media ? `${api.baseUrl}${media.url}` : null} text={text} />
      </div>
      <dl className="preview-details">
        <div><dt>Type</dt><dd>{typeLabel(entry)}</dd></div>
        {entry.size !== null && <div><dt>Taille</dt><dd>{formatSize(entry.size)}</dd></div>}
        <div><dt>Modifié</dt><dd>{formatDate(entry.modified)}</dd></div>
        <div><dt>Emplacement</dt><dd className="preview-path">{entry.path}</dd></div>
      </dl>
      <div className="preview-actions">
        {entry.is_dir && !entry.readable ? (
          <>
            <p className="preview-message">Windows protège ce dossier. Demande l'accès puis clique sur « Oui » dans la fenêtre de Windows : ce ne sera à faire qu'une fois.</p>
            <button className="button-primary" onClick={unlock} disabled={unlocking}>
              <KeyRound size={16} /> {unlocking ? "En attente de Windows…" : "Demander l'accès"}
            </button>
          </>
        ) : entry.is_dir ? (
          <button className="button-primary" onClick={() => onOpenFolder(entry.path)}>Ouvrir le dossier</button>
        ) : (
          <>
            <button className="button-primary ask-nova" onClick={() => onAskNova(entry)}><Sparkles size={16} /> Demander à NOVA</button>
            <div className="preview-row">
              <button className="button-secondary" onClick={() => run(() => openWithCheck((confirmed) => api.openFile(entry.path, confirmed)))}><ExternalLink size={15} /> Ouvrir</button>
              <button className="button-secondary" onClick={download} disabled={!media}><Download size={15} /> Télécharger</button>
            </div>
          </>
        )}
        {confirmTrash ? (
          <div className="preview-row preview-confirm">
            <span>Mettre à la corbeille ?</span>
            <button className="button-secondary danger-button" onClick={() => run(() => onTrash(entry))}>Oui</button>
            <button className="button-secondary" onClick={() => setConfirmTrash(false)}>Non</button>
          </div>
        ) : (
          <div className="preview-row">
            <button className="button-secondary" onClick={() => onStartRename(entry)}><Pencil size={15} /> Renommer</button>
            <button className="button-secondary" onClick={() => setConfirmTrash(true)}><Trash2 size={15} /> Corbeille</button>
          </div>
        )}
        {message && <p className="preview-message" role="status">{message}</p>}
      </div>
    </aside>
  );
};
