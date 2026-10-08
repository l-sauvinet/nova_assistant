import { FileText, LoaderCircle, X } from "lucide-react";
import type { UploadedAttachment } from "../lib/api";

export type PendingAttachment = {
  localId: string;
  name: string;
  previewUrl: string | null;
  status: "uploading" | "ready" | "error";
  error?: string;
  upload?: UploadedAttachment;
};

type AttachmentTrayProps = { attachments: PendingAttachment[]; onRemove: (localId: string) => void };

export const AttachmentTray = ({ attachments, onRemove }: AttachmentTrayProps) => {
  if (attachments.length === 0) return null;
  return (
    <ul className="attachment-tray" aria-label="Pièces jointes">
      {attachments.map((attachment) => (
        <li
          key={attachment.localId}
          className={`attachment-chip attachment-${attachment.status}${attachment.upload?.attachment.warning ? " attachment-suspicious" : ""}`}
          title={attachment.error ?? attachment.upload?.attachment.warning ?? attachment.name}
        >
          {attachment.previewUrl ? (
            <img src={attachment.previewUrl} alt="" />
          ) : (
            <span className="attachment-icon"><FileText size={18} aria-hidden="true" /></span>
          )}
          <span className="attachment-name">{attachment.status === "error" ? attachment.error : attachment.name}</span>
          {attachment.status === "uploading" && <LoaderCircle className="spin" size={15} aria-label="Envoi en cours" />}
          <button type="button" className="attachment-remove" onClick={() => onRemove(attachment.localId)} aria-label={`Retirer ${attachment.name}`}>
            <X size={13} />
          </button>
        </li>
      ))}
    </ul>
  );
};
