import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        crimson: "#990000",
        ink: "#243142",
        limestone: "#f8f5f0",
        mahogany: "#4a3c31",
        gold: "#e2b33c",
      },
      boxShadow: {
        soft: "0 10px 28px rgba(36, 49, 66, 0.08)",
      },
    },
  },
  plugins: [],
};

export default config;
