import { defineConfig } from "vite";

export default defineConfig({
  base: "./",
  build: {
    target: "chrome87",
    minify: false,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (/[\\/]node_modules[\\/](react|react-dom|scheduler)[\\/]/.test(id)) return "react";
        },
      },
    },
  },
});
