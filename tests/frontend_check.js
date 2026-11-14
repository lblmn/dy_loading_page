#!/usr/bin/env node
/* 前端静态自检（零依赖，node tests/frontend_check.js）
 * 1) 按 index.html 中 <script src> 的顺序合并编译：抓跨文件重复的 const/let/class
 *    声明（经典脚本共享全局词法作用域，重复声明会让整段脚本解析失败、按钮全部失效）
 * 2) 扫描各脚本顶层声明是否重名
 * 3) DOM id 一致性：三个页面与对应脚本的引用零缺失
 */
const fs = require('fs');
const vm = require('vm');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const S = f => fs.readFileSync(path.join(ROOT, 'static', f), 'utf8');
let failed = 0;
const report = (ok, label, detail = '') => {
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${label}${detail ? '  ' + detail : ''}`);
  if (!ok) failed++;
};

const indexHtml = S('index.html');
const scripts = [...indexHtml.matchAll(/<script src="\/static\/([\w.-]+\.js)"/g)].map(m => m[1]);
report(scripts.length >= 3, '解析 index.html 脚本加载顺序', scripts.join(' → '));

// 1) 合并编译（重复 const 在解析阶段即报错）
const merged = scripts.map(f => `// ---- ${f} ----\n${S(f)}`).join('\n');
try {
  new vm.Script(merged, { filename: 'merged.js' });
  report(true, '合并脚本编译通过（无重复顶层声明）');
} catch (e) {
  report(false, '合并脚本编译通过（无重复顶层声明）', `${e.name}: ${e.message}`);
}

// 2) 顶层声明重名
const seen = new Map();
const dup = [];
for (const f of scripts) {
  for (const name of [...S(f).matchAll(/^(?:const|let|var|function|class)\s+([\w$]+)/gm)].map(m => m[1])) {
    if (seen.has(name) && seen.get(name) !== f) dup.push(`${name} (${seen.get(name)} / ${f})`);
    seen.set(name, f);
  }
}
report(dup.length === 0, `顶层声明无跨文件重名（${seen.size} 个）`, dup.join(', '));

// 3) DOM id 一致性
const ids = html => new Set([...S(html).matchAll(/id="([^"]+)"/g)].map(m => m[1]));
const indexIds = ids('index.html'), landingIds = ids('landing.html'), adminIds = ids('admin.html');
const refs = (file, pattern) => new Set([...S(file).matchAll(pattern)].map(m => m[1]));
const appRefs = refs('app.js', /\$\('#([\w-]+)'\)/g);
const adminRefs = refs('admin.js', /\$\('#([\w-]+)'\)/g);
const landRefs = refs('landing.js', /\bq\('([\w-]+)'\)/g);
const missing = [
  ...[...appRefs].filter(x => !indexIds.has(x)).map(x => `app.js #${x}`),
  ...[...adminRefs].filter(x => !adminIds.has(x)).map(x => `admin.js #${x}`),
  ...[...landRefs].filter(x => !indexIds.has('ld-' + x) && !landingIds.has(x) && !indexIds.has(x))
    .map(x => `landing.js ${x}`),
];
report(missing.length === 0,
  `DOM id 引用零缺失（app ${appRefs.size} / admin ${adminRefs.size} / landing ${landRefs.size}）`,
  missing.join(', '));

const duplicates = [...indexIds].filter(x => (indexHtml.match(new RegExp(`id="${x.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}"`, 'g')) || []).length > 1);
report(duplicates.length === 0, 'index.html 无重复 id', duplicates.join(', '));

console.log(`\n前端自检：${failed ? failed + ' 项失败' : '全部通过'}`);
process.exit(failed ? 1 : 0);
