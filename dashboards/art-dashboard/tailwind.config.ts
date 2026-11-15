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
        gray: Object.fromEntries([50,100,200,300,400,500,600,700,800,900,950].map(n => [n, `rgb(var(--neutral-${n}) / <alpha-value>)`])),
        slate: Object.fromEntries([50,100,200,300,400,500,600,700,800,900,950].map(n => [n, `rgb(var(--neutral-${n}) / <alpha-value>)`])),
        panel: { DEFAULT: "rgb(var(--panel) / <alpha-value>)", hover: "rgb(var(--hover) / <alpha-value>)", border: "rgb(var(--border) / <alpha-value>)", active: "rgb(var(--surface) / <alpha-value>)" },
        accent: { DEFAULT: "rgb(var(--accent) / <alpha-value>)", hover: "rgb(var(--accent) / <alpha-value>)", muted: "#2563eb" },
        surface: { DEFAULT: "rgb(var(--surface) / <alpha-value>)", card: "rgb(var(--card) / <alpha-value>)", raised: "rgb(var(--panel) / <alpha-value>)" },
        flights: "#60a5fa", passengers: "#34d399", baggage: "#fb923c", incidents: "#f87171", weather: "#a78bfa", ground: "#fbbf24",
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
