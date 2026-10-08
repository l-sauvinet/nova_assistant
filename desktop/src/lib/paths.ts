import {
  File, FileArchive, FileAudio, FileCode, FileImage, FileSpreadsheet, FileText, FileVideo, Folder, Presentation,
  type LucideIcon,
} from "lucide-react";
import type { FileEntry } from "./api";

export type Crumb = { label: string; path: string };

export const breadcrumbs = (path: string): Crumb[] => {
  const windows = /^[A-Za-z]:[\\/]/.test(path);
  const separator = windows ? "\\" : "/";
  const parts = path.split(/[\\/]+/).filter(Boolean);
  if (windows) {
    const [drive, ...rest] = parts;
    const crumbs: Crumb[] = [{ label: `${drive.toUpperCase()}`, path: `${drive}\\` }];
    rest.forEach((part, index) => crumbs.push({ label: part, path: `${drive}\\${rest.slice(0, index + 1).join(separator)}` }));
    return crumbs;
  }
  if (parts[0] === "mnt" && parts[1]?.length === 1) {
    const drive = parts[1];
    const rest = parts.slice(2);
    const crumbs: Crumb[] = [{ label: `Disque ${drive.toUpperCase()}:`, path: `/mnt/${drive}` }];
    rest.forEach((part, index) => crumbs.push({ label: part, path: `/mnt/${drive}/${rest.slice(0, index + 1).join("/")}` }));
    return crumbs;
  }
  const crumbs: Crumb[] = [{ label: "Linux", path: "/" }];
  parts.forEach((part, index) => crumbs.push({ label: part, path: `/${parts.slice(0, index + 1).join("/")}` }));
  return crumbs;
};

const ICONS: Array<[LucideIcon, string[]]> = [
  [FileImage, ["jpg", "jpeg", "png", "webp", "gif", "bmp", "svg", "heic", "tif", "tiff"]],
  [FileText, ["pdf", "doc", "docx", "odt", "txt", "md", "rtf"]],
  [FileSpreadsheet, ["xls", "xlsx", "xlsm", "ods", "csv"]],
  [Presentation, ["ppt", "pptx", "odp", "key"]],
  [FileArchive, ["zip", "rar", "7z", "tar", "gz", "bz2", "xz"]],
  [FileAudio, ["mp3", "wav", "flac", "ogg", "m4a", "aac"]],
  [FileVideo, ["mp4", "mkv", "avi", "mov", "webm"]],
  [FileCode, ["py", "js", "ts", "tsx", "jsx", "json", "html", "css", "php", "java", "c", "cpp", "rs", "go", "sh", "yml", "yaml", "xml", "sql"]],
];

export const iconFor = (entry: Pick<FileEntry, "is_dir" | "extension">): LucideIcon => {
  if (entry.is_dir) return Folder;
  return ICONS.find(([, extensions]) => extensions.includes(entry.extension))?.[0] ?? File;
};

const TYPE_LABELS: Record<string, string> = {
  pdf: "Document PDF", docx: "Document Word", doc: "Document Word", xlsx: "Classeur Excel", xls: "Classeur Excel", csv: "Tableau CSV",
  pptx: "Présentation PowerPoint", txt: "Fichier texte", md: "Texte Markdown", jpg: "Image JPEG", jpeg: "Image JPEG", png: "Image PNG",
  gif: "Image GIF", webp: "Image WebP", svg: "Image SVG", zip: "Archive ZIP", mp3: "Audio MP3", mp4: "Vidéo MP4", html: "Page web",
  exe: "Programme", lnk: "Raccourci", py: "Code Python", js: "Code JavaScript", json: "Données JSON",
};

export const typeLabel = (entry: Pick<FileEntry, "is_dir" | "extension">) =>
  entry.is_dir ? "Dossier" : TYPE_LABELS[entry.extension] ?? (entry.extension ? `Fichier ${entry.extension.toUpperCase()}` : "Fichier");

export const PREVIEWABLE_IMAGES = ["jpg", "jpeg", "png", "webp", "gif", "bmp"];
export const PREVIEWABLE_TEXT = ["txt", "md", "csv", "json", "log", "py", "js", "ts", "tsx", "css", "html", "xml", "yml", "yaml", "sh", "ini", "sql"];

export const formatDate = (iso: string | null) => {
  if (!iso) return "—";
  const date = new Date(iso);
  const today = new Date();
  const sameDay = date.toDateString() === today.toDateString();
  return sameDay
    ? `Aujourd'hui, ${date.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}`
    : date.toLocaleDateString("fr-FR", { day: "numeric", month: "short", year: "numeric" });
};
