const RAW_API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined)
  ?.trim()
  .replace(/\/+$/, "");

const AUTH_ENDPOINT = RAW_API_BASE_URL
  ? `${RAW_API_BASE_URL}/auth/token`
  : "/auth/token";

const TOKEN_STORAGE_KEY = "art_dashboard_token";

let tokenPromise: Promise<string> | null = null;

function readStoredToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

function storeToken(token: string): void {
  try {
    window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
  } catch {
    // Ignore storage failures in restricted browser contexts.
  }
}

async function fetchGatewayToken(): Promise<string> {
  const res = await fetch(AUTH_ENDPOINT, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      client_id: "dashboard",
      secret: "art-dev-secret",
    }),
  });

  if (!res.ok) {
    throw new Error(`Failed to get auth token: ${res.status} ${res.statusText}`);
  }

  const data = (await res.json()) as { token?: string };
  if (!data.token) {
    throw new Error("Auth token missing from gateway response");
  }
  storeToken(data.token);
  return data.token;
}

export async function getAuthToken(forceRefresh = false): Promise<string> {
  if (!forceRefresh) {
    const cached = readStoredToken();
    if (cached) {
      return cached;
    }
  }

  if (!tokenPromise || forceRefresh) {
    tokenPromise = fetchGatewayToken().finally(() => {
      tokenPromise = null;
    });
  }

  return tokenPromise;
}
