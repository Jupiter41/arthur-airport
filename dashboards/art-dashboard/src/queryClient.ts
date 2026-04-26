import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchInterval: 15_000,
      retry: 2,
      staleTime: 10_000,
      refetchOnWindowFocus: false,
      refetchIntervalInBackground: false,
    },
  },
});
