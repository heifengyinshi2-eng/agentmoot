/**
 * pack.mjs —— 按 package.json 的 `files` 白名单组装发布快照目录。
 *
 * 为什么不能直接 `npm publish 仓库根`：npm 打包会读子目录里的 .gitignore，
 * 有时连 `files` 白名单都盖不过它（会把 demo/plans/node_modules 之类带进去）。
 * 先把白名单文件复制到干净目录 dist-release/，再从那里 pack/publish，
 * 发布内容就只由白名单决定。
 *
 * 用法：
 *   node scripts/release/pack.mjs          # 组装到 dist-release/
 *   node scripts/release/pack.mjs --pack   # 组装后顺便 npm pack 出 tgz
 */
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const OUT = path.join(REPO, "dist-release");
const pkg = JSON.parse(fs.readFileSync(path.join(REPO, "package.json"), "utf8"));

fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(OUT, { recursive: true });

const missing = [];
for (const rel of pkg.files) {
  const src = path.join(REPO, rel);
  const dst = path.join(OUT, rel);
  if (!fs.existsSync(src)) {
    missing.push(rel);
    continue;
  }
  fs.mkdirSync(path.dirname(dst), { recursive: true });
  fs.cpSync(src, dst, { recursive: true });
}
// package.json 必须进包（npm 以它为准）
fs.copyFileSync(path.join(REPO, "package.json"), path.join(OUT, "package.json"));

if (missing.length) {
  console.warn("⚠ 白名单中这些路径不存在，已跳过：");
  for (const m of missing) console.warn("  -", m);
}

console.log(`✓ 已组装发布目录：${path.relative(REPO, OUT)}/`);
console.log(`  包名 ${pkg.name}@${pkg.version}`);

if (process.argv.includes("--pack")) {
  const out = execFileSync("npm", ["pack"], { cwd: OUT, encoding: "utf8" }).trim();
  console.log("✓ npm pack 产物：", path.join(path.relative(REPO, OUT), out));
}
