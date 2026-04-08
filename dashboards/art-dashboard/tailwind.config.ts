/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        panel: {
          DEFAULT: "#1f2937", // gray-800
          hover: "#374151", // gray-700
          border: "#374151", // gray-700
          active: "#111827", // gray-900
        },
        accent: {
          DEFAULT: "#60a5fa", // blue-400
          hover: "#93bbfd", // blue-300
          muted: "#3b82f6", // blue-500
        },
      },
    },
  },
  plugins: [],
};
