/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Inter"', "system-ui", "-apple-system", "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "monospace"],
      },
      colors: {
        panel: {
          DEFAULT: "#1e2433",
          hover: "#2a3142",
          border: "#2f3749",
          active: "#141924",
        },
        accent: {
          DEFAULT: "#60a5fa",
          hover: "#93c5fd",
          muted: "#3b82f6",
        },
        surface: {
          DEFAULT: "#0f1219",
          card: "#171d2a",
          raised: "#1e2433",
        },
        // Section-specific accents for visual wayfinding
        flights: "#60a5fa",
        passengers: "#34d399",
        baggage: "#fb923c",
        incidents: "#f87171",
        weather: "#a78bfa",
        ground: "#fbbf24",
      },
      borderRadius: {
        "2xl": "1rem",
        "3xl": "1.25rem",
      },
      boxShadow: {
        glow: "0 0 20px -5px rgba(96, 165, 250, 0.15)",
        card: "0 1px 3px 0 rgba(0, 0, 0, 0.3), 0 1px 2px -1px rgba(0, 0, 0, 0.3)",
        "card-hover":
          "0 4px 12px 0 rgba(0, 0, 0, 0.4), 0 2px 4px -2px rgba(0, 0, 0, 0.3)",
      },
    },
  },
  plugins: [],
};
