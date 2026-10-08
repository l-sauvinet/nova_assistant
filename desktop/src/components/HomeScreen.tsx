import { ArrowRight, MapPin, UserRound } from "lucide-react";
import type { Status } from "../lib/api";
import { greetingFor } from "../lib/greeting";
import { SECTIONS, type SectionId } from "../lib/sections";
import { Orb, type OrbState } from "./Orb";

type HomeScreenProps = { status: Status; orbState: OrbState; onOpen: (section: SectionId) => void };

export const HomeScreen = ({ status, orbState, onOpen }: HomeScreenProps) => (
  <main className="home">
    <div className="home-hero">
      <Orb state={orbState} size={132} />
      <h1 className="greeting">{greetingFor(new Date())}.</h1>
      <p className="greeting-sub">Que veux-tu faire aujourd'hui ?</p>
      <div className="home-context">
        {status.location && <span className="chip"><MapPin size={14} aria-hidden="true" /> {status.location.city || status.location.label}</span>}
        {status.account && <span className="chip"><UserRound size={14} aria-hidden="true" /> {status.account.email}</span>}
      </div>
    </div>
    <div className="section-grid">
      {SECTIONS.map((section) => (
        <button key={section.id} className="section-card" onClick={() => onOpen(section.id)}>
          <span className="section-icon"><section.icon size={26} strokeWidth={1.7} aria-hidden="true" /></span>
          <span className="section-title">{section.title}</span>
          <span className="section-description">{section.description}</span>
          <span className="section-go">Ouvrir <ArrowRight size={15} aria-hidden="true" /></span>
        </button>
      ))}
    </div>
  </main>
);
