#!/usr/bin/env node
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";

const siteRoot = path.resolve(process.argv[2] ?? "sites");
const failures = [];

const skippedSchemes = /^(?:[a-z][a-z0-9+.-]*:|\/\/)/i;

function walk(dir) {
  const entries = readdirSync(dir, { withFileTypes: true });
  return entries.flatMap((entry) => {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      return walk(fullPath);
    }
    return entry.isFile() ? [fullPath] : [];
  });
}

function relative(file) {
  return path.relative(process.cwd(), file) || ".";
}

function addFailure(file, message) {
  failures.push(`${relative(file)}: ${message}`);
}

function stripQuotes(value) {
  return value.trim().replace(/^['"]|['"]$/g, "");
}

function splitUrl(rawValue) {
  const value = rawValue.trim().replace(/&amp;/g, "&");
  const hashIndex = value.indexOf("#");
  const beforeHash = hashIndex === -1 ? value : value.slice(0, hashIndex);
  const fragment = hashIndex === -1 ? "" : value.slice(hashIndex + 1);
  const queryIndex = beforeHash.indexOf("?");
  const pathname = queryIndex === -1 ? beforeHash : beforeHash.slice(0, queryIndex);

  return { value, pathname, fragment };
}

function decodePathname(ownerFile, pathname) {
  try {
    return decodeURI(pathname);
  } catch (error) {
    addFailure(ownerFile, `cannot decode local URL ${pathname}`);
    return null;
  }
}

function resolveTarget(ownerFile, pathname) {
  const decoded = decodePathname(ownerFile, pathname);
  if (decoded === null) {
    return null;
  }

  if (decoded === "" || decoded === ".") {
    return ownerFile;
  }

  if (decoded.startsWith("/")) {
    return path.join(siteRoot, decoded.slice(1));
  }

  return path.resolve(path.dirname(ownerFile), decoded);
}

function existingTarget(target, pathname) {
  if (!target) {
    return null;
  }

  if (existsSync(target)) {
    return statSync(target).isDirectory() ? path.join(target, "index.html") : target;
  }

  const candidates = [];
  if (pathname.endsWith("/")) {
    candidates.push(path.join(target, "index.html"));
  }
  if (!path.extname(target)) {
    candidates.push(`${target}.html`, path.join(target, "index.html"));
  }

  return candidates.find((candidate) => existsSync(candidate)) ?? null;
}

function hasAnchor(targetFile, fragment) {
  if (!fragment) {
    return true;
  }

  let decodedFragment;
  try {
    decodedFragment = decodeURIComponent(fragment);
  } catch (error) {
    return false;
  }

  const html = readFileSync(targetFile, "utf8");
  const escaped = decodedFragment.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const anchorPattern = new RegExp(`\\b(?:id|name)\\s*=\\s*(['"])${escaped}\\1`, "i");
  return anchorPattern.test(html);
}

function checkLocalUrl(ownerFile, rawValue, attribute = "url") {
  const { value, pathname, fragment } = splitUrl(stripQuotes(rawValue));

  if (!value) {
    if (attribute === "href") {
      addFailure(ownerFile, "empty href attribute");
    }
    return;
  }
  if (value === "#") {
    if (attribute === "href") {
      addFailure(ownerFile, "placeholder href #");
    }
    return;
  }
  if (skippedSchemes.test(value)) {
    return;
  }

  const target = existingTarget(resolveTarget(ownerFile, pathname), pathname);
  if (!target) {
    addFailure(ownerFile, `missing local resource ${value}`);
    return;
  }

  if (fragment && target.endsWith(".html") && !hasAnchor(target, fragment)) {
    addFailure(ownerFile, `missing fragment #${fragment} in ${relative(target)}`);
  }
}

function checkHtml(file) {
  const html = readFileSync(file, "utf8");
  const attrPattern = /\b(href|src)\s*=\s*(["'])(.*?)\2/gi;
  const srcsetPattern = /\bsrcset\s*=\s*(["'])(.*?)\1/gi;

  for (const match of html.matchAll(attrPattern)) {
    checkLocalUrl(file, match[3], match[1].toLowerCase());
  }

  for (const match of html.matchAll(srcsetPattern)) {
    for (const candidate of match[2].split(",")) {
      checkLocalUrl(file, candidate.trim().split(/\s+/)[0] ?? "");
    }
  }
}

function checkCss(file) {
  const css = readFileSync(file, "utf8");
  const urlPattern = /url\(\s*([^)]*?)\s*\)/gi;

  for (const match of css.matchAll(urlPattern)) {
    checkLocalUrl(file, match[1]);
  }
}

if (!existsSync(siteRoot) || !statSync(siteRoot).isDirectory()) {
  console.error(`Static site directory does not exist: ${siteRoot}`);
  process.exit(1);
}

const files = walk(siteRoot);
const htmlFiles = files.filter((file) => file.endsWith(".html"));
const cssFiles = files.filter((file) => file.endsWith(".css"));

if (htmlFiles.length === 0) {
  failures.push(`${relative(siteRoot)}: no HTML files found`);
}

htmlFiles.forEach(checkHtml);
cssFiles.forEach(checkCss);

if (failures.length) {
  console.error("Static site check failed:");
  failures.forEach((failure) => console.error(`- ${failure}`));
  process.exit(1);
}

console.log(`Static site check passed: ${htmlFiles.length} HTML file(s), ${cssFiles.length} CSS file(s).`);
