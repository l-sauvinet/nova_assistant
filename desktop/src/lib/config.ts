import { invoke, isTauri } from "@tauri-apps/api/core";

export type ServerConfig = { port: number; token: string };

export const loadServerConfig = async (): Promise<ServerConfig> => {
  if (isTauri()) {
    return invoke<ServerConfig>("server_config");
  }
  const token = import.meta.env.VITE_NOVA_TOKEN;
  if (!token) {
    throw new Error("VITE_NOVA_TOKEN manquant : lance l'interface avec `npm run dev:browser`.");
  }
  return { port: Number(import.meta.env.VITE_NOVA_PORT ?? 8765), token };
};
