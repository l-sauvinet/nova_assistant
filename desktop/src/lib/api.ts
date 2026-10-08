import type { ServerConfig } from "./config";
import type { MediaItem } from "./useChat";

export type Account = { email: string; everyday_login: boolean };

export type Location = {
  city: string;
  region: string;
  country: string;
  latitude: number;
  longitude: number;
  source: string;
  label: string;
};

export type Status = {
  provider: string;
  needs_account: boolean;
  account: Account | null;
  location: Location | null;
  trusted_dirs: string[];
};

export type ConversationSummary = { id: string; title: string; created_at: string; updated_at: string };

export type Place = { label: string; path: string; icon: string; group: string };

export type FileEntry = {
  name: string;
  path: string;
  is_dir: boolean;
  size: number | null;
  modified: string | null;
  extension: string;
  hidden: boolean;
  readable: boolean;
};

export type FolderListing = { path: string; name: string; parent: string | null; entries: FileEntry[]; truncated: boolean };

export type UploadedAttachment = { upload_id: string; attachment: MediaItem };

export type StoredItem =
  | { kind: "user"; text: string; attachments?: MediaItem[] }
  | { kind: "assistant" | "error"; text: string }
  | { kind: "tool"; id: string; name: string; arguments: Record<string, unknown>; status: "running" | "done" | "error"; media: MediaItem[]; warning?: string };

/** `ok: false` with a warning: the file may harm the computer; ask the user, then open again with `confirmed`. */
export type OpenResult = { ok: boolean; warning?: string };

export type ModelOption = { id: string; label: string; description: string };
export type Models = { current: string | null; options: ModelOption[] };

export class ApiError extends Error {}

export const ENGINE_UNREACHABLE = "NOVA ne répond pas pour le moment (son moteur redémarre ou est arrêté). Réessaie dans un instant.";

const reach = async (url: string, init: RequestInit): Promise<Response> => {
  try {
    return await fetch(url, init);
  } catch {
    throw new ApiError(ENGINE_UNREACHABLE);
  }
};

export type NovaApi = ReturnType<typeof createApi>;

export const createApi = (config: ServerConfig) => {
  const baseUrl = `http://127.0.0.1:${config.port}`;

  const request = async <T>(path: string, body?: unknown, method?: string): Promise<T> => {
    const response = await reach(`${baseUrl}${path}`, {
      method: method ?? (body === undefined ? "GET" : "POST"),
      headers: { Authorization: `Bearer ${config.token}`, "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new ApiError(payload.detail ?? `Erreur ${response.status}`);
    }
    return payload as T;
  };

  const uploadForm = async <T>(path: string, file: File): Promise<T> => {
    const form = new FormData();
    form.append("file", file, file.name);
    const response = await reach(`${baseUrl}${path}`, { method: "POST", headers: { Authorization: `Bearer ${config.token}` }, body: form });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new ApiError(payload.detail ?? `Erreur ${response.status}`);
    return payload as T;
  };

  return {
    baseUrl,
    chatUrl: `ws://127.0.0.1:${config.port}/ws?token=${encodeURIComponent(config.token)}`,
    status: () => request<Status>("/api/status"),
    accounts: () => request<{ current: Account | null; available: Account[] }>("/api/accounts"),
    selectAccount: (email: string) => request<{ account: Account }>("/api/accounts/select", { email }),
    startLogin: (email: string) => request<{ url: string; code_url: string }>("/api/accounts/login/start", { email }),
    loginStatus: () => request<{ account: Account | null }>("/api/accounts/login/status"),
    finishLogin: (code: string) => request<{ account: Account }>("/api/accounts/login/finish", { code }),
    models: () => request<Models>("/api/models"),
    selectModel: (model: string) => request<Models>("/api/models", { model }),
    switchAccount: () => request<{ ok: boolean }>("/api/accounts/switch", {}),
    removeAccount: (email: string) => request<{ available: Account[] }>("/api/accounts/remove", { email }),
    detectLocation: () => request<{ location: Location | null }>("/api/location/detect", {}),
    searchLocation: (place: string) => request<{ location: Location }>("/api/location/search", { place }),
    saveLocation: (location: Location) => request<{ location: Location }>("/api/location", location),
    conversations: () => request<{ current: string | null; conversations: ConversationSummary[] }>("/api/conversations"),
    newConversation: () => request<{ ok: boolean }>("/api/conversations/new", {}),
    openConversation: (id: string) =>
      request<{ conversation: ConversationSummary; items: StoredItem[] }>(`/api/conversations/${id}/open`, {}),
    renameConversation: (id: string, title: string) =>
      request<{ conversation: ConversationSummary }>(`/api/conversations/${id}/rename`, { title }),
    deleteConversation: (id: string) => request<{ ok: boolean }>(`/api/conversations/${id}`, undefined, "DELETE"),
    places: () => request<{ places: Place[] }>("/api/files/places"),
    listFolder: (path: string) => request<FolderListing>(`/api/files/list?path=${encodeURIComponent(path)}`),
    searchFiles: (path: string, query: string) =>
      request<{ root: string; query: string; entries: FileEntry[]; truncated: boolean }>(
        `/api/files/search?path=${encodeURIComponent(path)}&query=${encodeURIComponent(query)}`,
      ),
    thumbnailUrl: (path: string) =>
      `${baseUrl}/api/files/thumbnail?path=${encodeURIComponent(path)}&token_value=${encodeURIComponent(config.token)}`,
    previewFile: (path: string) => request<{ media: MediaItem }>("/api/files/preview", { path }),
    attachFile: (path: string) => request<UploadedAttachment>("/api/files/attach", { path }),
    createFolder: (parent: string, name: string) => request<{ entry: FileEntry }>("/api/files/folder", { parent, name }),
    renameFile: (path: string, name: string) => request<{ entry: FileEntry }>("/api/files/rename", { path, name }),
    trashFile: (path: string) => request<{ ok: boolean }>("/api/files/trash", { path }),
    openFile: (path: string, confirmed = false) => request<OpenResult>("/api/files/open", { path, confirmed }),
    requestAccess: (path: string) => request<{ entry: FileEntry }>("/api/files/request-access", { path }),
    uploadInto: (folder: string, file: File) => uploadForm<{ entry: FileEntry }>(`/api/files/upload?folder=${encodeURIComponent(folder)}`, file),
    upload: (file: File) => uploadForm<UploadedAttachment>("/api/uploads", file),
    openMedia: (id: string, confirmed = false) => request<OpenResult>(`/api/media/${id}/open`, { confirmed }),
    saveMedia: (id: string, destination: string) => request<{ path: string }>(`/api/media/${id}/save`, { destination }),
  };
};
