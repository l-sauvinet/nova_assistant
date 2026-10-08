import { isTauri } from "@tauri-apps/api/core";
import type { OpenResult } from "./api";

/** Native warning box (a browser confirm outside Tauri): the user decides whether to open a risky file. */
export const confirmRisk = async (warning: string): Promise<boolean> => {
  if (isTauri()) {
    const { ask } = await import("@tauri-apps/plugin-dialog");
    return ask(warning, { title: "NOVA — attention", kind: "warning", okLabel: "Ouvrir quand même", cancelLabel: "Annuler" });
  }
  return window.confirm(warning);
};

/** Opens a file; when the engine warns that it may harm the computer, asks first and opens only if accepted. */
export const openWithCheck = async (
  open: (confirmed: boolean) => Promise<OpenResult>,
  confirm: (warning: string) => Promise<boolean> = confirmRisk,
): Promise<boolean> => {
  const first = await open(false);
  if (first.ok) return true;
  if (!first.warning || !(await confirm(first.warning))) return false;
  return (await open(true)).ok;
};
