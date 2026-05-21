export function LoadingState({ message = "Loading…" }: { message?: string }) {
  return (
    <div className="flex items-center justify-center h-full text-gray-400">
      <div className="flex flex-col items-center gap-2">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500" />
        <span>{message}</span>
      </div>
    </div>
  );
}

export function ErrorState({
  message,
  detail,
  onRetry,
}: {
  message: string;
  detail?: string;
  onRetry?: () => void;
}) {
  return (
    <div className="flex items-center justify-center h-full text-gray-400">
      <div className="flex flex-col items-center gap-2 text-center">
        <span className="text-red-400 text-lg">⚠️ {message}</span>
        {detail && (
          <span className="text-sm text-gray-500 max-w-md">{detail}</span>
        )}
        {onRetry && (
          <button
            onClick={onRetry}
            className="mt-2 px-3 py-1 bg-blue-600 hover:bg-blue-700 rounded text-sm text-white"
          >
            Retry
          </button>
        )}
      </div>
    </div>
  );
}

export function EmptyState({
  icon = "💡",
  title,
  description,
}: {
  icon?: string;
  title: string;
  description: string;
}) {
  return (
    <div className="bg-amber-900/20 border border-amber-700/40 rounded-lg p-3 text-sm text-amber-300 flex items-start gap-2">
      <span className="text-lg">{icon}</span>
      <div>
        <strong>{title}</strong> {description}
      </div>
    </div>
  );
}
