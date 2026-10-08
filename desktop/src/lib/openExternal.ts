import { isTauri } from "@tauri-apps/api/core";

export const openExternal = async (url: string) => {
  if (isTauri()) {
    const { openUrl } = await import("@tauri-apps/plugin-opener");
    await openUrl(url);
  } else {
    window.open(url, "_blank", "noopener");
  }
};
