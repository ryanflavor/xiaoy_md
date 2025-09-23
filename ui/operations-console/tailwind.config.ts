import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        background: "#0F172A",
        surface: "#1E293B",
        primary: "#38BDF8",
        success: "#22C55E",
        warning: "#F97316",
        danger: "#F43F5E",
        neutral: {
          100: "#E2E8F0",
          300: "#94A3B8",
          500: "#64748B"
        },
      },
      fontFamily: {
        sans: ["Inter", "'Noto Sans SC'", "'Source Han Sans'", "sans-serif"],
      },
      boxShadow: {
        card: "0 16px 40px rgba(15, 23, 42, 0.48)",
      },
    },
  },
  plugins: [],
};

export default config;
