import { ArrowUp, Check, FileText, LoaderCircle, Paperclip, ShieldAlert, Upload, X } from "lucide-react";
import {
  useCallback, useEffect, useLayoutEffect, useRef, useState, type ClipboardEvent, type ComponentProps, type DragEvent, type KeyboardEvent,
  type ReactNode,
} from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { UploadedAttachment } from "../lib/api";
import { greetingFor } from "../lib/greeting";
import type { MediaActions } from "../lib/mediaActions";
import { openExternal } from "../lib/openExternal";
import type { ChatItem, MediaItem } from "../lib/useChat";
import { AttachmentTray, type PendingAttachment } from "./AttachmentTray";
import { MediaView } from "./MediaView";
import { Orb } from "./Orb";

type ChatScreenProps = {
  items: ChatItem[];
  busy: boolean;
  connected: boolean;
  mediaActions: MediaActions;
  onSend: (text: string, attachments: UploadedAttachment[]) => void;
  onUpload: (file: File) => Promise<UploadedAttachment>;
  queuedUploads?: UploadedAttachment[];
  onQueuedConsumed?: () => void;
  modelPicker?: ReactNode;
};

let localSequence = 0;

const MAX_COMPOSER_HEIGHT = 220;

const StepIcon = ({ status }: { status: "running" | "done" | "error" }) => {
  if (status === "running") return <LoaderCircle className="step-icon spin" size={15} aria-hidden="true" />;
  if (status === "done") return <Check className="step-icon" size={15} aria-hidden="true" />;
  return <X className="step-icon" size={15} aria-hidden="true" />;
};

const ChatEntry = ({ item, mediaActions }: { item: ChatItem; mediaActions: MediaActions }) => {
  switch (item.kind) {
    case "user":
      return (
        <div className="message-user-group">
          {item.attachments && item.attachments.length > 0 && (
            <div className="sent-attachments">
              {item.attachments.map((media) => <SentAttachment key={media.id} media={media} actions={mediaActions} />)}
            </div>
          )}
          {item.attachments?.flatMap((media) => (media.warning ? [<SecurityWarning key={`warning-${media.id}`} text={media.warning} />] : []))}
          {item.text && <div className="message message-user">{item.text}</div>}
        </div>
      );
    case "assistant":
      return (
        <div className="message message-assistant">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>{item.text}</ReactMarkdown>
        </div>
      );
    case "error":
      return <div className="message message-error" role="alert">{item.text}</div>;
    case "tool":
      return (
        <>
          <div className={`step step-${item.status}`}>
            <StepIcon status={item.status} />
            <span>{item.label}</span>
          </div>
          {item.warning && <SecurityWarning text={item.warning} />}
          {item.media?.map((media) => <MediaView key={media.id} media={media} actions={mediaActions} />)}
        </>
      );
  }
};

const EXTERNAL_LINK = /^(https?:|mailto:)/i;

/** Links in answers open in the user's browser, never inside NOVA's window (which a page could then imitate).
 * The real address is shown on hover, since the visible text of a link can say anything. */
const MarkdownLink = ({ href, children }: ComponentProps<"a">) =>
  href && EXTERNAL_LINK.test(href) ? (
    <a
      href={href}
      title={href}
      onClick={(event) => {
        event.preventDefault();
        void openExternal(href);
      }}
    >
      {children}
    </a>
  ) : (
    <span>{children}</span>
  );

const MARKDOWN_COMPONENTS = { a: MarkdownLink };

/** Content NOVA read looked like an attack on it (prompt injection): tell the user, who stays in charge. */
export const SecurityWarning = ({ text }: { text: string }) => (
  <div className="security-warning" role="alert">
    <ShieldAlert size={16} aria-hidden="true" />
    <span>{text} NOVA ne suivra pas ses instructions et te demandera avant toute action.</span>
  </div>
);

const SentAttachment = ({ media, actions }: { media: MediaItem; actions: MediaActions }) =>
  media.kind === "image" ? (
    <button type="button" className="sent-image" onClick={() => actions.open(media)} title={`Ouvrir ${media.file_name}`}>
      <img src={`${actions.baseUrl}${media.url}`} alt={media.file_name} />
    </button>
  ) : (
    <button type="button" className="sent-file" onClick={() => actions.open(media)} title={`Ouvrir ${media.file_name}`}>
      <FileText size={16} aria-hidden="true" /> <span>{media.file_name}</span>
    </button>
  );

const EmptyState = () => (
  <div className="empty-chat">
    <Orb state="idle" size={120} />
    <h1 className="greeting">{greetingFor(new Date())}.</h1>
    <p className="greeting-sub">Que puis-je faire pour toi ?</p>
  </div>
);

export const ChatScreen = ({ items, busy, connected, mediaActions, onSend, onUpload, queuedUploads = [], onQueuedConsumed, modelPicker }: ChatScreenProps) => {
  const [draft, setDraft] = useState("");
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const [dragging, setDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const uploading = attachments.some((attachment) => attachment.status === "uploading");
  const readyUploads = attachments.flatMap((attachment) => (attachment.upload ? [attachment.upload] : []));
  const canSend = connected && !busy && !uploading && (draft.trim().length > 0 || readyUploads.length > 0);

  const addFiles = (files: Iterable<File>) => {
    for (const file of files) {
      const localId = `local-${++localSequence}`;
      const previewUrl = file.type.startsWith("image/") ? URL.createObjectURL(file) : null;
      setAttachments((current) => [...current, { localId, name: file.name || "image collée", previewUrl, status: "uploading" }]);
      onUpload(file).then(
        (upload) => setAttachments((current) => current.map((item) => (item.localId === localId ? { ...item, status: "ready", upload } : item))),
        (reason: Error) =>
          setAttachments((current) => current.map((item) => (item.localId === localId ? { ...item, status: "error", error: reason.message } : item))),
      );
    }
  };

  useEffect(() => {
    if (queuedUploads.length === 0) return;
    setAttachments((current) => [
      ...current,
      ...queuedUploads.map((upload) => ({
        localId: `local-${++localSequence}`,
        name: upload.attachment.file_name,
        previewUrl: upload.attachment.kind === "image" ? `${mediaActions.baseUrl}${upload.attachment.url}` : null,
        status: "ready" as const,
        upload,
      })),
    ]);
    onQueuedConsumed?.();
    composerRef.current?.focus();
  }, [queuedUploads, onQueuedConsumed, mediaActions.baseUrl]);

  const removeAttachment = (localId: string) => setAttachments((current) => current.filter((item) => item.localId !== localId));

  const handleDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    if (event.dataTransfer.files.length) addFiles(Array.from(event.dataTransfer.files));
  };

  const handleDragOver = (event: DragEvent) => {
    if (!Array.from(event.dataTransfer.types).includes("Files")) return;
    event.preventDefault();
    setDragging(true);
  };

  const handlePaste = (event: ClipboardEvent<HTMLTextAreaElement>) => {
    const files = Array.from(event.clipboardData.files);
    if (files.length) {
      event.preventDefault();
      addFiles(files);
    }
  };

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [items, busy]);

  const fitComposer = useCallback(() => {
    const composer = composerRef.current;
    if (!composer || composer.offsetParent === null) return;
    composer.style.height = "auto";
    composer.style.height = `${Math.min(composer.scrollHeight, MAX_COMPOSER_HEIGHT)}px`;
    composer.style.overflowY = composer.scrollHeight > MAX_COMPOSER_HEIGHT ? "auto" : "hidden";
  }, []);

  useLayoutEffect(fitComposer, [draft, fitComposer]);

  useEffect(() => {
    const composer = composerRef.current;
    if (!composer || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(fitComposer);
    observer.observe(composer);
    return () => observer.disconnect();
  }, [fitComposer]);

  const send = (text: string) => {
    if (!canSend) return;
    onSend(text.trim(), readyUploads);
    setDraft("");
    setAttachments([]);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      send(draft);
    }
  };

  return (
    <div
      className="chat"
      onDragOver={handleDragOver}
      onDragLeave={(event) => event.currentTarget === event.target && setDragging(false)}
      onDrop={handleDrop}
    >
      {dragging && (
        <div className="drop-overlay" onDragLeave={() => setDragging(false)}>
          <Upload size={34} aria-hidden="true" />
          <p>Dépose tes fichiers ici</p>
          <span className="muted">Photos, PDF, Word, Excel, PowerPoint, texte…</span>
        </div>
      )}
      <div className="chat-scroll" aria-live="polite">
        <div className="chat-column">
          {items.length === 0 ? (
            <EmptyState />
          ) : (
            items.map((item) => <ChatEntry key={item.id} item={item} mediaActions={mediaActions} />)
          )}
          {busy && <div className="thinking">NOVA réfléchit…</div>}
          <div ref={bottomRef} />
        </div>
      </div>
      <form className="composer-dock" onSubmit={(event) => { event.preventDefault(); send(draft); }}>
        <AttachmentTray attachments={attachments} onRemove={removeAttachment} />
        <div className="composer">
          <input
            ref={fileInputRef}
            type="file"
            multiple
            hidden
            data-testid="file-input"
            onChange={(event) => {
              if (event.target.files) addFiles(Array.from(event.target.files));
              event.target.value = "";
            }}
          />
          <button type="button" className="attach-button" onClick={() => fileInputRef.current?.click()} aria-label="Joindre des fichiers" title="Joindre des fichiers">
            <Paperclip size={19} />
          </button>
          <textarea
            ref={composerRef}
            aria-label="Message pour NOVA"
            placeholder={connected ? "Demande n'importe quoi à NOVA…" : "Connexion à NOVA…"}
            value={draft}
            rows={1}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={handleKeyDown}
            onPaste={handlePaste}
          />
          {modelPicker}
          <button type="submit" className="send-button" disabled={!canSend} aria-label="Envoyer">
            <ArrowUp size={18} strokeWidth={2.5} />
          </button>
        </div>
        <p className="composer-hint">Entrée pour envoyer · Maj+Entrée pour aller à la ligne · Glisse ou colle des fichiers pour les joindre</p>
      </form>
    </div>
  );
};
