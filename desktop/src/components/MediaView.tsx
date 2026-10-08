import { useState } from "react";
import type { MediaActions } from "../lib/mediaActions";
import type { MediaItem } from "../lib/useChat";

type MediaViewProps = { media: MediaItem; actions: MediaActions };

const FILE_TYPES: Record<string, { label: string; icon: string }> = {
  pdf: { label: "Document PDF", icon: "📕" },
  docx: { label: "Document Word", icon: "📘" },
  html: { label: "Page web", icon: "🌐" },
  md: { label: "Texte Markdown", icon: "📝" },
  txt: { label: "Fichier texte", icon: "📄" },
  csv: { label: "Tableau CSV", icon: "📊" },
  svg: { label: "Image SVG", icon: "🎨" },
  jpg: { label: "Image", icon: "🖼️" },
  png: { label: "Image", icon: "🖼️" },
  webp: { label: "Image", icon: "🖼️" },
};

const extensionOf = (fileName: string) => fileName.split(".").pop()?.toLowerCase() ?? "";

export const formatSize = (bytes: number) => {
  if (bytes < 1024) return `${bytes} o`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} Ko`;
  return `${(bytes / (1024 * 1024)).toFixed(1).replace(".", ",")} Mo`;
};

const Preview = ({ media, url }: { media: MediaItem; url: string }) => {
  if (media.kind === "image" || media.kind === "svg") {
    return <img className="media-preview-image" src={url} alt={media.title} />;
  }
  if (media.kind === "html") {
    return <iframe title={media.title} src={url} sandbox="allow-scripts" />;
  }
  if (extensionOf(media.file_name) === "pdf") {
    return <iframe title={media.title} src={url} />;
  }
  return null;
};

export const MediaView = ({ media, actions }: MediaViewProps) => {
  const [status, setStatus] = useState<string | null>(null);
  const url = `${actions.baseUrl}${media.url}`;
  const type = FILE_TYPES[extensionOf(media.file_name)] ?? { label: "Fichier", icon: "📄" };

  const run = async (action: () => Promise<string | null | void>, success?: (result: string) => string) => {
    setStatus(null);
    try {
      const result = await action();
      if (typeof result === "string" && success) setStatus(success(result));
    } catch (reason) {
      setStatus(reason instanceof Error ? reason.message : String(reason));
    }
  };

  return (
    <figure className={`media media-${media.kind}`}>
      <Preview media={media} url={url} />
      <figcaption>
        <span className="media-icon" aria-hidden="true">{type.icon}</span>
        <span className="media-text">
          <strong>{media.title}</strong>
          <span className="muted">{type.label} · {formatSize(media.size)}</span>
        </span>
        <span className="media-buttons">
          <button type="button" className="button-secondary" onClick={() => run(() => actions.open(media))}>Ouvrir</button>
          <button type="button" className="button-primary" onClick={() => run(() => actions.download(media), (path) => `Enregistré : ${path}`)}>
            Télécharger
          </button>
        </span>
      </figcaption>
      {status && <p className="media-status muted" role="status">{status}</p>}
    </figure>
  );
};
