export type OrbState = "idle" | "thinking" | "working" | "asking" | "offline";

type OrbProps = { state: OrbState; size?: number };

const STATE_LABELS: Record<OrbState, string> = {
  idle: "NOVA est prêt",
  thinking: "NOVA réfléchit",
  working: "NOVA agit sur l'ordinateur",
  asking: "NOVA attend ton accord",
  offline: "NOVA est déconnecté",
};

export const Orb = ({ state, size = 36 }: OrbProps) => (
  <div className="orb" data-state={state} style={{ width: size, height: size }} role="img" aria-label={STATE_LABELS[state]}>
    <div className="orb-glow" />
    <div className="orb-core" />
    <div className="orb-swirl" />
    <div className="orb-shine" />
  </div>
);
