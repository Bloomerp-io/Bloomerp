import { createRequire } from "node:module";
import path from "node:path";
import process from "node:process";

const appRoot = path.resolve(process.argv[2]);
const files = process.argv.slice(3).map((file) => path.resolve(file));
const appRequire = createRequire(path.join(appRoot, "package.json"));
const sourceRequire = createRequire(path.join(path.dirname(files[0] ?? appRoot), "package.json"));
const localRequire = createRequire(import.meta.url);

let ts;
try {
  ts = appRequire("typescript");
} catch {
  try {
    ts = sourceRequire("typescript");
  } catch {
    try {
      ts = localRequire("typescript");
    } catch {
      process.stderr.write(
        "TypeScript is required for frontend message extraction. Install it in the project running bloomerp_i18n.\n",
      );
      process.exit(2);
    }
  }
}

const messages = [];
const literal = (node) =>
  ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node) ? node.text : null;

for (const filename of files) {
  const source = ts.createSourceFile(
    filename,
    ts.sys.readFile(filename) ?? "",
    ts.ScriptTarget.Latest,
    true,
    filename.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );

  const visit = (node) => {
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression)) {
      const name = node.expression.text;
      let message = null;
      let context = null;
      if (name === "t" || name === "_") message = literal(node.arguments[0]);
      if (name === "tn") {
        const singular = literal(node.arguments[0]);
        const plural = literal(node.arguments[1]);
        if (singular !== null && plural !== null) message = [singular, plural];
      }
      if (name === "tp") {
        context = literal(node.arguments[0]);
        message = literal(node.arguments[1]);
      }
      if (message !== null && (name !== "tp" || context !== null)) {
        const position = source.getLineAndCharacterOfPosition(node.getStart(source));
        messages.push({
          message,
          context,
          locations: [[path.relative(appRoot, filename), position.line + 1]],
        });
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
}

process.stdout.write(JSON.stringify(messages));
