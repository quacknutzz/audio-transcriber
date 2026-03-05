const { spawn } = require('child_process');
const path = require('path');

const electronBinary = path.join(__dirname, 'node_modules', 'electron', 'dist', 'electron.exe');

console.log('Spawning Electron explicitly without shell variable inheritance...');
const child = spawn(electronBinary, ['.'], {
    env: { ...process.env, ELECTRON_RUN_AS_NODE: undefined },
    stdio: 'inherit'
});

child.on('exit', (code) => {
    process.exit(code);
});
