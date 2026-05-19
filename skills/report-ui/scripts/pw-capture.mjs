// Playwright reproduction capture — launches the BUILT app in a clean state
// and screenshots the chat panel. This is a "reference baseline" shot, not the
// contributor's live session (use capture-window.sh for that).
//
// Run from the repo's e2e/ dir so @playwright/test resolves:
//   cd e2e && node ../.claude/skills/report-ui/scripts/pw-capture.mjs <out.png>
import { _electron as electron } from "@playwright/test";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

const OUT = process.argv[2];
if (!OUT) { console.error("usage: pw-capture.mjs <out.png>"); process.exit(2); }

const REPO = path.resolve(process.cwd(), "..");
const APP = path.join(REPO, "vscodium-base/VSCode-darwin-arm64/HypeProof Studio.app/Contents/MacOS/HypeProof Studio");
const TOKEN_FILE = "/tmp/hps-token.txt";

if (!fs.existsSync(APP)) { console.error(`ERR app missing: ${APP}`); process.exit(3); }
const token = fs.existsSync(TOKEN_FILE) ? fs.readFileSync(TOKEN_FILE, "utf8").trim() : "";

const udd = fs.mkdtempSync(path.join(os.tmpdir(), "hps-report-"));
const userDir = path.join(udd, "User");
fs.mkdirSync(userDir, { recursive: true });
fs.writeFileSync(path.join(userDir, "settings.json"), JSON.stringify({
  "hypeproofChat.proxyUrl": "http://localhost:8787/v1",
  "workbench.startupEditor": "none",
  "telemetry.telemetryLevel": "off",
  "update.mode": "none",
}, null, 2));
fs.writeFileSync(path.join(userDir, "hps-test-state.json"),
  JSON.stringify(token ? { token } : {}));

const app = await electron.launch({
  executablePath: APP,
  args: [
    `--user-data-dir=${udd}`,
    `--extensions-dir=${path.join(udd, "extensions")}`,
    "--disable-workspace-trust", "--password-store=basic",
    "--disable-updates", "--skip-welcome", "--skip-release-notes", "--no-sandbox",
  ],
  env: { ...process.env, ...(token ? { HPS_TEST_TOKEN: token } : {}) },
});
try {
  const win = await app.firstWindow();
  await win.waitForTimeout(6000); // let the extension host + webview mount
  await win.screenshot({ path: OUT, fullPage: true });
  console.log(OUT);
} finally {
  await app.close();
  fs.rmSync(udd, { recursive: true, force: true });
}
