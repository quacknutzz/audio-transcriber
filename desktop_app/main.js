const electron = require('electron');
const app = electron.app;
const BrowserWindow = electron.BrowserWindow;

const { spawn } = require('child_process');
const path = require('path');
const waitOn = require('wait-on');
const treeKill = require('tree-kill');

let mainWindow;
let backendProcess;
let frontendProcess;

function startBackend() {
    const backendDir = path.join(__dirname, '..', 'backend');
    const pythonExecutable = path.join(backendDir, 'venv', 'Scripts', 'python.exe');

    console.log(`Starting FastAPI backend...`);
    backendProcess = spawn(pythonExecutable, ['main.py'], {
        cwd: backendDir,
        shell: true,
        env: { ...process.env, PYTHONUTF8: '1' }
    });

    backendProcess.stdout.on('data', (data) => console.log(`Backend: ${data}`));
    backendProcess.stderr.on('data', (data) => console.error(`Backend Error: ${data}`));
}

function startFrontend() {
    const frontendDir = path.join(__dirname, '..', 'frontend');

    // Need node in PATH if running outside usual terminal
    const userPath = process.env.PATH || '';
    const nodePath = 'C:\\Program Files\\nodejs';
    const customPath = userPath.includes(nodePath) ? userPath : `${userPath};${nodePath}`;

    console.log(`Starting Next.js frontend...`);
    frontendProcess = spawn('npm.cmd', ['run', 'dev'], {
        cwd: frontendDir,
        env: { ...process.env, PATH: customPath },
        shell: true,
    });

    frontendProcess.stdout.on('data', (data) => console.log(`Frontend: ${data}`));
    frontendProcess.stderr.on('data', (data) => console.error(`Frontend Error: ${data}`));
}

function createWindow() {
    mainWindow = new BrowserWindow({
        width: 1200,
        height: 800,
        title: "Audio Transcriber",
        autoHideMenuBar: true,
        webPreferences: {
            nodeIntegration: false,
            contextIsolation: true
        }
    });

    // Wait for the Next.js target to be responsive
    console.log("Waiting for Next.js server to be ready on port 3000...");

    mainWindow.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent('<html><body style="background:#111;color:white;display:flex;align-items:center;justify-content:center;font-family:sans-serif;height:100vh;margin:0;"><h1>Starting Audio Transcriber Servers...</h1><p style="margin-top:10px;text-align:center;">This may take a minute.</p></body></html>'));

    waitOn({ resources: ['http://127.0.0.1:3000'], timeout: 60000 })
        .then(() => {
            console.log("Next.js server is ready. Loading window...");
            mainWindow.loadURL('http://127.0.0.1:3000');
        })
        .catch((err) => {
            console.error("Failed to connect to Next.js server:", err);
            mainWindow.loadURL('data:text/html,' + encodeURIComponent(`<h2>Error starting application</h2><p>${err}</p>`));
        });

    mainWindow.on('closed', () => {
        mainWindow = null;
    });
}

// When Electron is ready
app.whenReady().then(() => {
    startBackend();
    startFrontend();
    createWindow();

    app.on('activate', () => {
        if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
});

// Kill all child processes aggressively
function cleanupProcesses() {
    console.log('Shutting down services...');
    if (backendProcess && backendProcess.pid) {
        try { treeKill(backendProcess.pid, 'SIGKILL'); } catch (e) { /* ignore */ }
    }
    if (frontendProcess && frontendProcess.pid) {
        try { treeKill(frontendProcess.pid, 'SIGKILL'); } catch (e) { /* ignore */ }
    }
    // Safety net: force-kill anything still on our ports
    const { execSync } = require('child_process');
    try {
        execSync('for /f "tokens=5" %a in (\'netstat -aon ^| findstr ":3000" ^| findstr "LISTENING"\') do taskkill /F /PID %a', { shell: true, stdio: 'ignore' });
    } catch (e) { /* nothing on port */ }
    try {
        execSync('for /f "tokens=5" %a in (\'netstat -aon ^| findstr ":8000" ^| findstr "LISTENING"\') do taskkill /F /PID %a', { shell: true, stdio: 'ignore' });
    } catch (e) { /* nothing on port */ }
}

// Clean up on every possible exit signal
app.on('before-quit', cleanupProcesses);
app.on('will-quit', cleanupProcesses);
process.on('SIGINT', () => { cleanupProcesses(); process.exit(); });
process.on('SIGTERM', () => { cleanupProcesses(); process.exit(); });
process.on('uncaughtException', (err) => { console.error('Uncaught:', err); cleanupProcesses(); process.exit(1); });

app.on('window-all-closed', () => {
    cleanupProcesses();
    if (process.platform !== 'darwin') {
        app.quit();
    }
});
