import { useState } from "react";
import type { Location, NovaApi } from "../lib/api";

type LocationBannerProps = {
  api: NovaApi;
  onSaved: (location: Location) => void;
  onClose: () => void;
};

export const LocationBanner = ({ api, onSaved, onClose }: LocationBannerProps) => {
  const [proposal, setProposal] = useState<Location | null>(null);
  const [place, setPlace] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [working, setWorking] = useState(false);

  const run = async (action: () => Promise<void>) => {
    setWorking(true);
    setMessage(null);
    try {
      await action();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setWorking(false);
    }
  };

  const detect = () =>
    run(async () => {
      const { location } = await api.detectLocation();
      if (location) setProposal(location);
      else setMessage("Position introuvable : tape ta ville.");
    });

  const search = () => run(async () => setProposal((await api.searchLocation(place.trim())).location));
  const save = (location: Location) => run(async () => onSaved((await api.saveLocation(location)).location));

  return (
    <div className="banner" role="region" aria-label="Position">
      {proposal ? (
        <>
          <span>Position : <strong>{proposal.label}</strong></span>
          <button className="button-primary" disabled={working} onClick={() => save(proposal)}>C'est bon</button>
          <button className="button-secondary" onClick={() => setProposal(null)}>Changer</button>
        </>
      ) : (
        <>
          <span>NOVA a besoin de ta position pour la météo et les questions locales.</span>
          <button className="button-primary" disabled={working} onClick={detect}>{working ? "Détection…" : "Détecter"}</button>
          <form onSubmit={(event) => { event.preventDefault(); if (place.trim()) search(); }}>
            <input aria-label="Ville" placeholder="ou tape ta ville" value={place} onChange={(event) => setPlace(event.target.value)} />
          </form>
          <button className="link-button" onClick={onClose}>Plus tard</button>
        </>
      )}
      {message && <span className="error-text">{message}</span>}
    </div>
  );
};
