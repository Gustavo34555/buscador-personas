/* Evita que index.html y el service worker se versionen por separado. */
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const sw = fs.readFileSync(path.join(root, 'sw.js'), 'utf8');

function assert(cond, msg) {
  if (!cond) {
    console.error('FALLO: ' + msg);
    process.exit(1);
  }
}

for (const name of ['styles.css', 'app.js']) {
  const re = name === 'app.js' ? /app\.js\?v=([0-9.]+)/g : /styles\.css\?v=([0-9.]+)/g;
  const htmlVersion = html.match(re);
  const swVersion = sw.match(re);
  assert(htmlVersion && htmlVersion.length === 1, `${name}: versión única en index.html`);
  assert(swVersion && swVersion.length === 1, `${name}: versión única en sw.js`);
  assert(htmlVersion[0] === swVersion[0], `${name}: ${htmlVersion[0]} ≠ ${swVersion[0]}`);
}

const version = sw.match(/const VERSION = '([^']+)'/);
assert(version, 'sw.js debe definir VERSION');
assert(sw.includes('SHELL_URL = `/index.html?v=${VERSION}`'), 'SHELL_URL debe usar VERSION');

console.log('VERSION CHECK OK');
