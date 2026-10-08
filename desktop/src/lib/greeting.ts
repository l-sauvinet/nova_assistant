export const greetingFor = (date: Date) => {
  const hour = date.getHours();
  if (hour >= 5 && hour < 18) return "Bonjour";
  return "Bonsoir";
};
