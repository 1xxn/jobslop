import { fileURLToPath, URL } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Gebaut wird direkt ins Python-Paket, damit `jobslop` die Oberfläche ohne Node ausliefern kann.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  build: {
    outDir: "../src/jobslop/web/dist",
    emptyOutDir: true,
    rolldownOptions: {
      output: {
        // Bibliotheken getrennt vom App-Code: nach einem Update lädt der Browser nur den geänderten App-Teil neu
        advancedChunks: {
          groups: [
            { name: "react", test: /node_modules[\\/](react|react-dom|react-router|scheduler)[\\/]/ },
            { name: "vendor", test: /node_modules[\\/]/ },
          ],
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8765",
      "/artifacts": "http://127.0.0.1:8765",
    },
  },
});
