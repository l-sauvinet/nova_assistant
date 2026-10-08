import { useEffect, useRef } from "react";
import type { ConfirmationRequest } from "../lib/useChat";
import { Orb } from "./Orb";

type ConfirmDialogProps = {
  request: ConfirmationRequest;
  onAnswer: (approved: boolean) => void;
};

export const ConfirmDialog = ({ request, onAnswer }: ConfirmDialogProps) => {
  const refuseButton = useRef<HTMLButtonElement>(null);
  const [intro, ...detailLines] = request.question.split("\n");
  const details = detailLines.join("\n").trimEnd();
  const warning = request.warning ?? null;

  useEffect(() => {
    refuseButton.current?.focus();
  }, [request.id]);

  return (
    <div className="dialog-backdrop">
      <div className="dialog" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" aria-describedby="confirm-question">
        <div className="dialog-header">
          <Orb state="asking" size={30} />
          <h2 id="confirm-title">NOVA demande ton accord</h2>
        </div>
        <div className="dialog-body">
          {warning && <p className="dialog-warning" role="alert">{warning}</p>}
          <p id="confirm-question">{intro}</p>
          {details && (
            // With a warning, what will really run matters more than the summary written by the model: show it.
            <details className="dialog-technical" open={Boolean(warning)}>
              <summary>Voir le détail technique</summary>
              <pre className="dialog-details">{details}</pre>
            </details>
          )}
        </div>
        <div className="dialog-actions">
          <button ref={refuseButton} className="button-secondary" onClick={() => onAnswer(false)}>
            Refuser
          </button>
          <button className="button-primary" onClick={() => onAnswer(true)}>
            Autoriser
          </button>
        </div>
      </div>
    </div>
  );
};
