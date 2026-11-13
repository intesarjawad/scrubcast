import { defineConfig } from "vite";

export default defineConfig({
  base: process.env.SITE_URL ? new URL(process.env.SITE_URL).pathname : "/",
});
