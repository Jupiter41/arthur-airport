import { useWebSocket } from "../hooks/useWebSocket";

/**
 * Invisible component that manages the WebSocket connection.
 * Isolated from the render tree so WS-triggered store updates
 * don't cascade re-renders through AppShell → Routes.
 */
export function WebSocketManager() {
  useWebSocket();
  return null;
}
