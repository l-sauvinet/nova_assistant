# NOVA — Networked Operations & Voice Assistant

Assistant IA personnel : boucle agent, 3 providers interchangeables, CLI.

Outils : fichiers (lister, lire, créer, modifier, déplacer, supprimer, rechercher), taille des dossiers,
infos système (date, RAM, CPU, disques, processus), recherche web (DuckDuckGo) et lecture de pages,
commandes bash (chaque commande est validée par toi avant exécution, désactivable avec `NOVA_SHELL_ENABLED=false`).

## Installation

```bash
uv sync
cp .env.example .env    # puis éditer NOVA_PROVIDER et NOVA_ALLOWED_DIRS
mkdir -p ~/nova-workspace
uv run nova setup       # détecte ta position (localisation Windows, sinon adresse IP) et l'enregistre dans .env
```

`nova setup` se lance aussi tout seul au premier démarrage si la position n'est pas encore connue.
Pour la localisation Windows : Paramètres Windows → Confidentialité → Localisation doit être activé.

Selon le provider choisi dans `.env` :

| `NOVA_PROVIDER` | Prérequis |
|---|---|
| `claude_code` | CLI Claude Code installée. Chaque conversation garde sa propre session Claude Code (`~/.nova/claude-sessions`) : seul le nouveau message est envoyé, le reste est relu depuis le cache (bien moins de consommation). Au premier lancement, NOVA demande quel compte Claude utiliser (ta connexion Claude Code habituelle, ou un autre compte ajouté depuis ce menu). Le choix est gardé jusqu'à `/logout` (dans le chat) ou `uv run nova logout`. Aucun coût API : utilise l'abonnement du compte choisi. |
| `anthropic` | `ANTHROPIC_API_KEY` dans `.env` (modèle par défaut : Claude Haiku 4.5). |
| `ollama` | Ollama côté Linux : `curl -fsSL https://ollama.com/install.sh \| sh`, puis `ollama pull qwen2.5:7b`. |

## Lancement

```bash
uv run nova
```

Le modèle se choisit dans le menu à côté de la barre de message de l'app (Haiku, Sonnet, Opus, Fable) ; le choix est gardé dans `.env`.

Commandes : `/reset` (efface la conversation), `/logout` (change de compte Claude au prochain lancement), `/quit`.
NOVA peut accéder à tout le PC. Les dossiers de `NOVA_TRUSTED_DIRS` sont ouverts sans question ; pour tout autre dossier, NOVA demande la permission (lecture, ou lecture + modification), une fois par dossier et par session. Supprimer, déplacer ou écraser un fichier demande en plus une confirmation.

## Tests

```bash
uv run pytest
```

Les tests n'appellent jamais de vraie IA : ils utilisent un provider factice (`tests/fakes.py`), et `tests/conftest.py` bloque tout accès réseau et tout sous-processus (`claude -p`). Un test qui tenterait un vrai appel échoue immédiatement.

## Structure

```
src/nova/
  config.py        configuration (.env)
  prompts/         prompt système de NOVA
  core/            boucle agent + messages neutres        → futur backend FastAPI
  providers/       claude_code, anthropic, ollama         → futur backend FastAPI
  tools/           outils exécutés en local (un fichier par famille) → future app Tauri
  interfaces/      CLI (plus tard : API, voix)
```

À venir : mails (IMAP/SMTP) dans `tools/`, API FastAPI et voix (faster-whisper, Piper, mot de réveil « Nova ») dans `interfaces/`, app Tauri.

## App bureau (en cours : étape 1)

L'app s'ouvre sur une page d'accueil avec ses sections (la liste est dans `desktop/src/lib/sections.ts`) :
- **Assistant** : discussions avec historique (`~/.nova/conversations/`), pièces jointes (photos, PDF, Word,
  Excel, PowerPoint, texte…) par trombone, glisser-déposer ou Ctrl+V, fichiers créés présentés en cartes
  (aperçu, Ouvrir, Télécharger).
- **Fichiers** : explorateur de tout le PC (dossiers Windows, disques, Linux), aperçu, recherche, nouveau dossier,
  renommer (sur place, ou F2), corbeille, dépôt de fichiers, et « Demander à NOVA » pour envoyer un fichier dans une discussion.
  Les dossiers que Windows bloque (profils d'autres comptes…) sont masqués ; en affichant les fichiers cachés, ils
  apparaissent avec un cadenas et « Demander l'accès » (fenêtre administrateur de Windows, une fois par dossier, lecture seule).

L'app (`desktop/`, Tauri + React) lance le moteur Python (`nova serve`, serveur local sur 127.0.0.1
protégé par un jeton) et affiche le chat, les confirmations, le choix du compte Claude et la position.

Prérequis (une fois) : Rust (`~/.cargo/bin`) et les bibliothèques système :

```bash
sudo apt install -y libwebkit2gtk-4.1-dev libxdo-dev libssl-dev libayatana-appindicator3-dev librsvg2-dev nsis lld llvm clang
cd desktop && npm install
```

Lancer l'app en développement (fenêtre native via WSLg) :

```bash
cd desktop && PATH="$HOME/.cargo/bin:$PATH" npm run tauri dev
```

Sans Rust, dans un navigateur : `npm run engine:dev` dans un terminal, `npm run dev:browser` dans un autre, puis ouvrir http://localhost:1420.

Tests de l'interface : `cd desktop && npm test`.

## Licence

NOVA est un logiciel libre et gratuit, distribué sous licence [MIT](LICENSE).
