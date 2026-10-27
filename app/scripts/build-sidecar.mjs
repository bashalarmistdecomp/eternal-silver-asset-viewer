// Freeze the viewer's Python backend into one executable for the release
// bundle, and write the bundle's third-party notices: `npm run bundle` runs
// this, then `tauri build` with src-tauri/tauri.standalone.conf.json, which
// ships both beside the app. Node, so it runs the same on Linux, macOS and
// Windows.
//
//   backend/server.py + viewer_server/ + viewer_tabs/ + decoders/
//   + Pillow + numpy
//   -> src-tauri/binaries/eternal-silver-asset-viewer-backend-<target triple>[.exe]
//   -> src-tauri/notices/THIRD-PARTY-NOTICES.txt     (tools/notices.py)
//
// The freeze runs in its own venv (app/.sidecar-venv), so PyInstaller never
// enters the repository's .venv. Its packages are pinned by
// backend/requirements-sidecar.txt: the backend's own, and PyInstaller. The
// venv is made from $ASSET_VIEWER_PYTHON, else from the Python the
// repository's .venv was made from (the version the decoders are tested
// on), else from python3 (python on Windows).

import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, readdirSync, renameSync, rmSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const APP = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const ROOT = dirname(APP)
const BACKEND = join(ROOT, 'backend')
const VENV = join(APP, '.sidecar-venv')
const WORK = join(APP, '.sidecar-build')
const OUT = join(APP, 'src-tauri', 'binaries')
const NOTICES = join(APP, 'src-tauri', 'notices', 'THIRD-PARTY-NOTICES.txt')
const NAME = 'eternal-silver-asset-viewer-backend'
const WINDOWS = process.platform === 'win32'

const run = (cmd, args) => execFileSync(cmd, args, { stdio: 'inherit' })
const read = (cmd, args) => execFileSync(cmd, args, { encoding: 'utf8' })
/** A venv's interpreter. */
const pythonOf = (venv) => (WINDOWS ? join(venv, 'Scripts', 'python.exe') : join(venv, 'bin', 'python3'))

// Tauri looks for <name>-<target triple>; ask rustc which triple this is.
const triple = read('rustc', ['-vV']).match(/^host: (\S+)$/m)?.[1]
if (!triple) throw new Error('build-sidecar: rustc did not say its host triple')

function basePython() {
  if (process.env.ASSET_VIEWER_PYTHON) return process.env.ASSET_VIEWER_PYTHON
  const repo = pythonOf(join(ROOT, '.venv'))
  if (existsSync(repo)) return read(repo, ['-c', 'import sys; print(sys._base_executable)']).trim()
  return WINDOWS ? 'python' : 'python3'
}

const python = pythonOf(VENV)
if (!existsSync(python)) {
  const base = basePython()
  console.log(`build-sidecar: creating ${VENV} from ${base}`)
  run(base, ['-m', 'venv', VENV])
}
run(python, ['-m', 'pip', 'install', '-q', '-r', join(BACKEND, 'requirements-sidecar.txt')])

/**
 * Every module of the backend's packages but their tests'. The decoders reach
 * their plugins and record layouts, and the links their domains, by name
 * (importlib) as well as by plain imports, so each module is named to the
 * freeze rather than left to its reading of the imports. (PyInstaller's
 * --collect-submodules cannot do it: it runs before --paths is in effect,
 * finds no package, and collects nothing, silently.)
 */
function backendModules() {
  const out = []
  const walk = (dir, name) => {
    for (const e of readdirSync(dir, { withFileTypes: true })) {
      if (e.isDirectory()) {
        if (e.name !== 'tests' && existsSync(join(dir, e.name, '__init__.py'))) walk(join(dir, e.name), `${name}.${e.name}`)
      } else if (e.name.endsWith('.py') && !e.name.startsWith('test_') && e.name !== 'conftest.py') {
        out.push(e.name === '__init__.py' ? name : `${name}.${e.name.slice(0, -3)}`)
      }
    }
  }
  for (const pkg of ['decoders', 'viewer_tabs', 'viewer_server']) walk(join(BACKEND, pkg), pkg)
  // what only the tests read
  return out.filter((m) => m !== 'decoders.testing').sort()
}

const modules = backendModules()
console.log(`build-sidecar: ${modules.length} modules of the backend named to the freeze`)
mkdirSync(OUT, { recursive: true })
// --onefile unpacks the runtime to a temporary folder at every start and
// removes it when the backend exits, which is why the app closes the
// backend's stdin to stop it rather than killing it
// (src-tauri/src/backend.rs, Backend::stop).
run(python, [
  '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile',
  '--name', NAME,
  '--distpath', OUT, '--workpath', WORK, '--specpath', WORK,
  '--paths', BACKEND,
  ...modules.flatMap((m) => ['--hidden-import', m]),
  '--exclude-module', 'tkinter',
  '--log-level', 'WARN',
  join(BACKEND, 'server.py'),
])

const ext = WINDOWS ? '.exe' : ''
const named = join(OUT, `${NAME}-${triple}${ext}`)
rmSync(named, { force: true })
renameSync(join(OUT, NAME + ext), named)
console.log(`build-sidecar: ${named}`)

// The notices are written by the freeze's interpreter: the Python packages
// it lists are the ones frozen.
run(python, [join(ROOT, 'tools', 'notices.py'), '--target', triple, '--out', NOTICES])
