import { useEffect, useRef, type ReactNode } from "react";

/** Native modal supplies focus containment, Escape and inert background. */
export function Dialog({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const previous = document.activeElement;
    ref.current?.showModal();
    return () => { if (previous instanceof HTMLElement && previous.isConnected) previous.focus(); };
  }, []);
  return <dialog ref={ref} aria-label={title} onCancel={e => { e.preventDefault(); onClose(); }} className="app-dialog" onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
    <div className="flex justify-between items-center gap-4 mb-5"><h2 className="text-lg">{title}</h2><button className="btn-secondary" aria-label={`Close ${title}`} onClick={onClose}>Close</button></div>
    {children}
  </dialog>;
}
