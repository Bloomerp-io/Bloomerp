import { mkdir, cp, copyFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const root = path.resolve(__dirname, '..');

const cssSrc = path.join(
	root,
	'node_modules',
	'@fortawesome',
	'fontawesome-free',
	'css',
	'all.min.css'
);
const webfontsSrc = path.join(
	root,
	'node_modules',
	'@fortawesome',
	'fontawesome-free',
	'webfonts'
);

const destBase = path.join(root, '..', 'static', 'bloomerp', 'vendor', 'fontawesome');
const cssDestDir = path.join(destBase, 'css');
const webfontsDestDir = path.join(destBase, 'webfonts');

async function main() {
	if (!existsSync(cssSrc)) {
		throw new Error(`Font Awesome CSS not found at: ${cssSrc}`);
	}
	if (!existsSync(webfontsSrc)) {
		throw new Error(`Font Awesome webfonts not found at: ${webfontsSrc}`);
	}

	await mkdir(cssDestDir, { recursive: true });
	await mkdir(webfontsDestDir, { recursive: true });

	await copyFile(cssSrc, path.join(cssDestDir, 'all.min.css'));
	await cp(webfontsSrc, webfontsDestDir, { recursive: true, force: true });
}

main().catch((err) => {
	// eslint-disable-next-line no-console
	console.error(err);
	process.exitCode = 1;
});
