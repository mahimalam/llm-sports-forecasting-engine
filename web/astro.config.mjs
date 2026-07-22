import { defineConfig } from "astro/config";
import sitemap from "@astrojs/sitemap";

export default defineConfig({
  site: "https://vexp.me",
  output: "static",
  markdown: { shikiConfig: { theme: "dracula" } },
  integrations: [
    sitemap({
      filter: (page) => !page.includes('_'),
      serialize(item) {
        // Match and team pages get high priority + today's lastmod
        if (item.url.includes('/matches/') || item.url.includes('/teams/')) {
          item.priority = 0.9;
          item.lastmod = new Date().toISOString();
        } else if (item.url === 'https://vexp.me/' || item.url.includes('/predictions/') || item.url.includes('/live/')) {
          item.priority = 1.0;
          item.lastmod = new Date().toISOString();
        } else {
          item.priority = 0.6;
        }
        // Exclude report pages from sitemap
        if (item.url.includes('-report')) return undefined;
        return item;
      },
    }),
  ],
});
