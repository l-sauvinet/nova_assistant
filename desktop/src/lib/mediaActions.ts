import { isTauri } from "@tauri-apps/api/core";
import type { NovaApi } from "./api";
import { openWithCheck } from "./safeOpen";
import type { MediaItem } from "./useChat";

export type MediaActions = {
  baseUrl: string;
  open: (media: MediaItem) => Promise<void>;
  download: (media: MediaItem) => Promise<string | null>;
};

export const createMediaActions = (api: NovaApi): MediaActions => ({
  baseUrl: api.baseUrl,
  open: async (media) => {
    await openWithCheck((confirmed) => api.openMedia(media.id, confirmed));
  },
  download: async (media) => {
    if (isTauri()) {
      const { save } = await import("@tauri-apps/plugin-dialog");
      const destination = await save({ defaultPath: media.file_name, title: "Enregistrer le fichier" });
      if (!destination) return null;
      return (await api.saveMedia(media.id, destination)).path;
    }
    const link = document.createElement("a");
    link.href = `${api.baseUrl}${media.url}?download=true`;
    link.download = media.file_name;
    link.click();
    return null;
  },
});
