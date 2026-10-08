import { Check, ChevronDown } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { Models, NovaApi } from "../lib/api";

type ModelPickerProps = { api: NovaApi; disabled: boolean; onError: (message: string) => void };

export const ModelPicker = ({ api, disabled, onError }: ModelPickerProps) => {
  const [models, setModels] = useState<Models | null>(null);
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.models().then(setModels, () => setModels(null));
  }, [api]);

  useEffect(() => {
    if (!open) return;
    const closeOnOutside = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => event.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", closeOnOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("mousedown", closeOnOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  if (!models || models.options.length === 0) return null;
  const current = models.options.find((option) => option.id === models.current);

  const choose = async (id: string) => {
    setOpen(false);
    if (id === models.current) return;
    try {
      setModels(await api.selectModel(id));
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : String(reason));
    }
  };

  return (
    <div className="model-picker" ref={rootRef}>
      <button
        type="button"
        className="model-button"
        onClick={() => setOpen(!open)}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        title={disabled ? "Attends la fin de la réponse pour changer de modèle" : "Changer de modèle"}
      >
        {current?.label ?? "Modèle par défaut"} <ChevronDown size={14} aria-hidden="true" />
      </button>
      {open && (
        <ul className="model-menu" role="listbox" aria-label="Modèle">
          {models.options.map((option) => (
            <li key={option.id}>
              <button type="button" role="option" aria-selected={option.id === models.current} onClick={() => choose(option.id)}>
                <span className="model-option-text">
                  <span>{option.label}</span>
                  <span className="muted">{option.description}</span>
                </span>
                {option.id === models.current && <Check size={16} aria-hidden="true" />}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};
