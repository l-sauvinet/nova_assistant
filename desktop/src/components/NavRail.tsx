import { House, LogOut } from "lucide-react";
import { SECTIONS, type SectionId } from "../lib/sections";
import { Orb, type OrbState } from "./Orb";

export type View = "home" | SectionId;

type NavRailProps = { view: View; orbState: OrbState; canLogOut: boolean; onNavigate: (view: View) => void; onLogOut: () => void };

export const NavRail = ({ view, orbState, canLogOut, onNavigate, onLogOut }: NavRailProps) => (
  <nav className="nav-rail" aria-label="Navigation principale">
    <button className="nav-orb" onClick={() => onNavigate("home")} aria-label="Accueil" title="Accueil">
      <Orb state={orbState} size={30} />
    </button>
    <button className={`nav-item ${view === "home" ? "active" : ""}`} onClick={() => onNavigate("home")} aria-current={view === "home" ? "page" : undefined} title="Accueil">
      <House size={20} aria-hidden="true" />
      <span>Accueil</span>
    </button>
    {SECTIONS.map((section) => (
      <button
        key={section.id}
        className={`nav-item ${view === section.id ? "active" : ""}`}
        onClick={() => onNavigate(section.id)}
        aria-current={view === section.id ? "page" : undefined}
        title={section.title}
      >
        <section.icon size={20} aria-hidden="true" />
        <span>{section.title}</span>
      </button>
    ))}
    <div className="nav-spacer" />
    {canLogOut && (
      <button className="nav-item" onClick={onLogOut} title="Changer de compte Claude">
        <LogOut size={19} aria-hidden="true" />
        <span>Compte</span>
      </button>
    )}
  </nav>
);
