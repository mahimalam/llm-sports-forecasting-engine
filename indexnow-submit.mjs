#!/usr/bin/env node
// indexnow-submit.mjs — submits all site URLs to IndexNow (Bing, Yandex, etc.)
// Usage: node indexnow-submit.mjs
// Run after every deploy or daily via cron.

import { readdir } from "fs/promises";
import { resolve } from "path";

const HOST = "vexp.me";
const KEY = "5fe66e500af64cf9982d3e6c777616a6";
const KEY_LOCATION = `https://${HOST}/${KEY}.txt`;
const DIST = resolve(import.meta.dirname ?? ".", "web/dist");

async function getSlugs(subdir) {
  try {
    const entries = await readdir(resolve(DIST, subdir), { withFileTypes: true });
    return entries
      .filter(e => e.isDirectory() && !e.name.includes("report") && !e.name.startsWith("_"))
      .map(e => `https://${HOST}/${subdir}/${e.name}/`);
  } catch { return []; }
}

const matchUrls = await getSlugs("matches");
const teamUrls = await getSlugs("teams");

const urls = [
  `https://${HOST}/`,
  `https://${HOST}/live/`,
  `https://${HOST}/matches/`,
  `https://${HOST}/predictions/`,
  `https://${HOST}/standings/`,
  `https://${HOST}/teams/`,
  ...matchUrls,
  ...teamUrls,
].map(u => encodeURI(u));

console.log(`Submitting ${urls.length} URLs to IndexNow...`);

// IndexNow API (used by Bing, Yandex, Seznam)
const res = await fetch("https://api.indexnow.org/indexnow", {
  method: "POST",
  headers: { "Content-Type": "application/json; charset=utf-8" },
  body: JSON.stringify({ host: HOST, key: KEY, keyLocation: KEY_LOCATION, urlList: urls }),
});
console.log(`IndexNow: ${res.status} ${res.status === 200 ? "OK" : await res.text()}`);

// Also ping Bing directly
const bingRes = await fetch("https://www.bing.com/indexnow", {
  method: "POST",
  headers: { "Content-Type": "application/json; charset=utf-8" },
  body: JSON.stringify({ host: HOST, key: KEY, keyLocation: KEY_LOCATION, urlList: urls }),
});
console.log(`Bing: ${bingRes.status} ${bingRes.status === 200 ? "OK" : await bingRes.text()}`);
