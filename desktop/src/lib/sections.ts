import { FolderOpen, MessageCircle, type LucideIcon } from "lucide-react";

export type SectionId = "chat" | "files";

export type Section = { id: SectionId; title: string; description: string; icon: LucideIcon };

/** Sections of the app, shown on the home page and in the navigation rail. Add new ones here. */
export const SECTIONS: Section[] = [
  { id: "chat", title: "Assistant", description: "Discute avec NOVA : questions, documents, images, actions sur ton PC.", icon: MessageCircle },
  { id: "files", title: "Fichiers", description: "Parcours tout ton ordinateur, prévisualise, range et envoie tes fichiers à NOVA.", icon: FolderOpen },
];
