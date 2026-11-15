import { useEffect, useRef, type ReactNode } from "react";

/** Native modal supplies focus containment, Escape and inert background. */
export function Dialog({
  title,
  children,
  onClose,
  returnFocus,
  className = "",
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  returnFocus?: HTMLElement | null;
  className?: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const previous = returnFocus ?? document.activeElement;
    ref.current?.showModal();
    return () => {
      if (previous instanceof HTMLElement && previous.isConnected)
        queueMicrotask(() => previous.focus());
    };
  }, []);
  return (
    <dialog
      ref={ref}
      aria-label={title}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      className={`app-dialog ${className}`}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="flex justify-between items-center gap-4 mb-5">
        <h2 className="text-lg">{title}</h2>
        <button
          className="btn-secondary"
          aria-label={`Close ${title}`}
          onClick={onClose}
        >
          Close
        </button>
      </div>
      {children}
    </dialog>
  );
}
