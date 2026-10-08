import type { ConversationSummary } from "./api";

export type ConversationGroup = { label: string; conversations: ConversationSummary[] };

const DAY_MS = 24 * 60 * 60 * 1000;

const startOfDay = (date: Date) => new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();

const labelFor = (updatedAt: string, now: Date) => {
  const daysAgo = Math.round((startOfDay(now) - startOfDay(new Date(updatedAt))) / DAY_MS);
  if (daysAgo <= 0) return "Aujourd'hui";
  if (daysAgo === 1) return "Hier";
  if (daysAgo < 7) return "7 derniers jours";
  if (daysAgo < 30) return "30 derniers jours";
  return "Plus ancien";
};

export const groupConversations = (conversations: ConversationSummary[], now: Date = new Date()): ConversationGroup[] => {
  const groups: ConversationGroup[] = [];
  const sorted = [...conversations].sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  for (const conversation of sorted) {
    const label = labelFor(conversation.updated_at, now);
    const group = groups.find((candidate) => candidate.label === label);
    if (group) group.conversations.push(conversation);
    else groups.push({ label, conversations: [conversation] });
  }
  return groups;
};

export const filterConversations = (conversations: ConversationSummary[], query: string) => {
  const needle = query.trim().toLocaleLowerCase("fr");
  return needle ? conversations.filter((conversation) => conversation.title.toLocaleLowerCase("fr").includes(needle)) : conversations;
};
