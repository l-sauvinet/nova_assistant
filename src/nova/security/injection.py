"""Spots content that looks written to manipulate NOVA rather than to be read (instructions aimed at the AI,
hidden characters, data sent to a site), and commands that download and run code.

This is a warning light, not a wall: a determined attacker can always rephrase. What actually protects the
user is `Exposure`, which asks before acting once outside content was read, whether or not it was flagged.
The patterns stay narrow on purpose: a warning that fires on ordinary pages soon gets ignored.
"""

import re

FLAGS = re.IGNORECASE | re.MULTILINE

AI_INSTRUCTIONS = [
    r"\b(ignore|disregard|forget|override)\b.{0,40}\b(previous|prior|above|earlier|all|your|system)\b.{0,20}\b(instructions?|prompts?|rules|directives)\b",
    r"\b(ignore|ignorez|oublie|oubliez)\b.{0,40}\b(tes|vos|les|toutes)\b.{0,30}\b(instructions?|consignes|règles|directives)\b",
    r"\byou are now (a|an) (new |different )?(ai|assistant|model|bot|agent)\b",
    r"\b(tu es|vous êtes) (maintenant|désormais) (un|une) (nouvel(le)? )?(ia|assistant|agent|bot|modèle)\b",
    r"\bfrom now on,? you (must|will|should|are)\b",
    r"\b(new|updated) (system )?instructions?\s*:",
    r"\bnouvelles? (consignes|instructions)\s*:",
    r"\b(do not|don't|never) (tell|inform|mention|alert|show)\b.{0,20}\b(the )?user\b.{0,15}\b(about|that you|what you|this|these)\b",
    r"\bne (le |lui )?(dis|dites|signale|signalez|montre|montrez) (rien|pas)\b.{0,30}\butilisateur\b",
    r"\bsans (le |en )?(prévenir|avertir|informer)\b.{0,20}\butilisateur\b",
    r"\b(note|message|instructions?|consignes?) (to|for|à|pour) (the |l')?(ai|ia|assistant|llm|chatbot|claude|nova)( \w+)?\s*:",
    r"^\s*\[(system|developer|instructions?)\]",
    r"<\|(im_start|im_end|system|endoftext)\|>",
    r"</?(system|instructions)>",
]

DANGEROUS_COMMANDS = [
    r"\b(curl|wget|iwr|irm|invoke-webrequest|invoke-restmethod)\b[^\n|]*\|\s*(sh|bash|zsh|iex|invoke-expression|powershell|pwsh|python3?)\b",
    r"\b(iex|invoke-expression)\b\s*[\(\$]",
    r"\b(powershell|pwsh)(\.exe)?\b[^\n]*\s-(e|ec|enc|encodedcommand)\s+[a-z0-9+/=]{20,}",
    r"\bcertutil(\.exe)?\b[^\n]*-urlcache",
    r"\bbitsadmin(\.exe)?\b[^\n]*/transfer",
    r"\bmshta(\.exe)?\s+(https?|vbscript|javascript):",
    r"\b(regsvr32|rundll32)(\.exe)?\b[^\n]*(https?://|javascript:)",
    r"\breg(\.exe)?\s+add\b[^\n]*\\(run|runonce)\b",
    r"\bset-mppreference\b[^\n]*-disable",
    r"\badd-mppreference\b[^\n]*-exclusion",
    r"\brm\s+-[a-z]*r[a-z]*\s+(/|~/?|\$home/?|/mnt/c/?)(\*|\s|$)",
    r"\bremove-item\b[^\n]*-recurse[^\n]*(\bc:\\(\*|\s|$)|\$env:userprofile|\$home\b)",
    r"\bformat(\.com)?\s+[a-z]:",
    r"\bvssadmin\b[^\n]*delete\s+shadows",
    r"\bschtasks(\.exe)?\b[^\n]*/create\b",
    r"\\start menu\\programs\\startup\b",
]

DATA_LEAKS = [
    r"!\[[^\]]*\]\(\s*https?://[^)\s]*\?[^)\s]*=",
    r"\b(send|post|upload|exfiltrate|envoie|envoyer|transmets|transmettre)\b.{0,40}\b(contents?|contenu|files?|fichiers?|data|données|conversation|history|historique|passwords?|mots? de passe|tokens?|keys?|clés?)\b.{0,60}https?://",
]

INVISIBLE_TAGS = re.compile("[\U000e0000-\U000e007f]")
BIDI_CONTROLS = re.compile("[‪-‮⁦-⁩]")
ZERO_WIDTH = re.compile("[​-‍⁠-⁤﻿]")
ZERO_WIDTH_TOLERATED = 4

_DANGEROUS_COMMANDS = [re.compile(pattern, FLAGS) for pattern in DANGEROUS_COMMANDS]
# Dangerous commands are not looked for in content: install guides are full of `curl ... | sh`. They are
# checked where they matter, in the command NOVA is about to run (risky_command).
_CHECKS = [
    ([re.compile(pattern, FLAGS) for pattern in AI_INSTRUCTIONS], "des instructions adressées à l'IA"),
    ([re.compile(pattern, FLAGS) for pattern in DATA_LEAKS], "une tentative d'envoyer des données vers un site"),
]


def scan(text: str) -> list[str]:
    """What looks hostile in `text`, as short French phrases for the user (empty: nothing spotted)."""
    findings = [label for patterns, label in _CHECKS if any(pattern.search(text) for pattern in patterns)]
    hidden_characters = len(ZERO_WIDTH.findall(text.lstrip("﻿"))) > ZERO_WIDTH_TOLERATED
    if INVISIBLE_TAGS.search(text) or BIDI_CONTROLS.search(text) or hidden_characters:
        findings.append("du texte caché en caractères invisibles")
    return findings


def risky_command(command: str) -> bool:
    return any(pattern.search(command) for pattern in _DANGEROUS_COMMANDS)
