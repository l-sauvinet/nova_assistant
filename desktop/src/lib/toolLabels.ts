type Arguments = Record<string, unknown>;

const MAX_LABEL_LENGTH = 90;

const text = (value: unknown, fallback = "") => (typeof value === "string" && value.trim() ? value.trim() : fallback);

const shortPath = (value: unknown, fallback: string) => {
  const path = text(value);
  if (!path || path === "." || path === "~") return fallback;
  const parts = path.replace(/[\\/]+$/, "").split(/[\\/]/);
  return parts[parts.length - 1] || path;
};

const siteName = (value: unknown) => {
  try {
    return new URL(text(value)).hostname.replace(/^www\./, "");
  } catch {
    return "une page web";
  }
};

const LABELS: Record<string, (args: Arguments) => string> = {
  list_directory: (args) => `Ouverture du dossier ${shortPath(args.path, "de travail")}`,
  read_file: (args) => `Lecture de ${shortPath(args.path, "un fichier")}`,
  create_file: (args) => `Création de ${shortPath(args.path, "un fichier")}`,
  edit_file: (args) => `Modification de ${shortPath(args.path, "un fichier")}`,
  move_path: (args) => `Déplacement de ${shortPath(args.source, "un élément")} vers ${shortPath(args.destination, "un dossier")}`,
  delete_path: (args) => `Suppression de ${shortPath(args.path, "un élément")}`,
  search_files: (args) => (text(args.text) ? `Recherche des fichiers contenant « ${text(args.text)} »` : "Recherche de fichiers"),
  folder_sizes: (args) => `Calcul de la place prise par ${shortPath(args.path, "ton dossier personnel")}`,
  system_info: () => "Consultation des infos de l'ordinateur",
  list_processes: () => "Liste des programmes en cours",
  web_search: (args) => `Recherche sur internet : ${text(args.query)}`,
  fetch_page: (args) => `Lecture de ${siteName(args.url)}`,
  run_command: (args) => text(args.explanation, "Action sur l'ordinateur"),
  generate_image: (args) => `Création d'une image : ${text(args.prompt)}`,
  create_artifact: (args) => `Création de « ${text(args.title)} »`,
};

const truncate = (label: string) =>
  label.length > MAX_LABEL_LENGTH ? `${label.slice(0, MAX_LABEL_LENGTH - 1).trimEnd()}…` : label;

export const describeTool = (name: string, args: Arguments): string =>
  truncate(LABELS[name]?.(args) ?? "Action en cours");
