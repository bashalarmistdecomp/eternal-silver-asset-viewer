//! The Python backend: finding it, starting it, and knowing whether it is up.
//!
//! Every decoder is Python (`backend/decoders`), and so is the viewer's tab
//! logic (`backend/viewer_tabs`). The window therefore decodes nothing: it
//! starts `backend/server.py` and the UI talks to that over HTTP on
//! 127.0.0.1. Two ways to run it, tried in order:
//!
//! 1. **A bundled sidecar** — `eternal-silver-asset-viewer-backend[.exe]`
//!    next to this executable, frozen by `scripts/build-sidecar.mjs`
//!    (PyInstaller) for a release build (`npm run bundle`). Needs no Python on the machine.
//! 2. **The repository's own** — `<repo>/.venv/bin/python3
//!    <repo>/backend/server.py`, for a debug build made in a checkout of
//!    this repository (`tauri dev`). A release build has no such fallback,
//!    and carries no path of the machine that built it.
//!
//! Either way the backend gets `--watch-stdin`, so it exits when this
//! process does, however it ends, and `--library <folder>` when one was
//! chosen; without it the backend uses its default library folder.

use std::collections::VecDeque;
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};

/// Lines of backend output kept for the setup screen when it fails.
const LOG_LINES: usize = 200;
/// How long the backend may take to print its READY line.
const START_TIMEOUT: Duration = Duration::from_secs(90);
/// How long the backend has to exit once its stdin is closed, before it is killed.
const STOP_GRACE: Duration = Duration::from_secs(2);

#[derive(Serialize, Clone, Debug)]
#[serde(tag = "state", rename_all = "kebab-case")]
pub enum State {
    Starting,
    Ready {
        port: u16,
        token: String,
        library: String,
    },
    Error {
        message: String,
        log: Vec<String>,
    },
}

#[derive(Deserialize)]
struct ReadyLine {
    ready: bool,
    port: u16,
    token: String,
    library: String,
}

#[derive(Default)]
pub struct Backend {
    state: Mutex<Option<State>>,
    child: Mutex<Option<Arc<Mutex<Child>>>>,
    log: Arc<Mutex<VecDeque<String>>>,
    /// Bumped on every (re)start, so a dying old process cannot report over a new one.
    generation: Mutex<u64>,
}

/// A pipe's lines until it closes, each read as UTF-8 with anything else
/// replaced. A line in another encoding (a Windows code page) must not end
/// the reading: the pipe would close, and the backend's next write to it fail.
fn lossy_lines(pipe: impl std::io::Read) -> impl Iterator<Item = String> {
    let mut reader = BufReader::new(pipe);
    std::iter::from_fn(move || {
        let mut line = Vec::new();
        match reader.read_until(b'\n', &mut line) {
            Ok(0) | Err(_) => None,
            Ok(_) => {
                while matches!(line.last(), Some(b'\n' | b'\r')) {
                    line.pop();
                }
                Some(String::from_utf8_lossy(&line).into_owned())
            }
        }
    })
}

fn push_log(log: &Mutex<VecDeque<String>>, line: String) {
    let mut log = log.lock().unwrap_or_else(|p| p.into_inner());
    if log.len() >= LOG_LINES {
        log.pop_front();
    }
    log.push_back(line);
}

/// The checkout this binary was built in, if it is still there:
/// src-tauri -> app -> the repository root. Debug builds only.
#[cfg(debug_assertions)]
fn build_repo() -> Option<PathBuf> {
    let here = Path::new(env!("CARGO_MANIFEST_DIR"));
    let repo = here.ancestors().nth(2)?.to_path_buf();
    repo.join("backend")
        .join("server.py")
        .is_file()
        .then_some(repo)
}

#[cfg(not(debug_assertions))]
fn build_repo() -> Option<PathBuf> {
    None
}

fn sidecar() -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    let name = if cfg!(windows) {
        "eternal-silver-asset-viewer-backend.exe"
    } else {
        "eternal-silver-asset-viewer-backend"
    };
    let path = exe.parent()?.join(name);
    path.is_file().then_some(path)
}

fn repo_python(repo: &Path) -> PathBuf {
    let venv = if cfg!(windows) {
        repo.join(".venv").join("Scripts").join("python.exe")
    } else {
        repo.join(".venv").join("bin").join("python3")
    };
    if venv.is_file() {
        venv
    } else {
        PathBuf::from(if cfg!(windows) { "python" } else { "python3" })
    }
}

/// The command that runs the backend, or why there is none.
fn command(library: Option<&Path>) -> Result<Command, String> {
    let mut cmd = if let Some(bin) = sidecar() {
        Command::new(bin)
    } else if let Some(repo) = build_repo() {
        let mut c = Command::new(repo_python(&repo));
        c.arg(repo.join("backend").join("server.py"));
        c
    } else {
        return Err(
            "This build has no bundled backend, and is no debug build of a \
                    checkout. Build the app with `npm run bundle`."
                .into(),
        );
    };
    cmd.arg("--watch-stdin");
    if let Some(library) = library {
        cmd.arg("--library").arg(library);
    }
    cmd.env("PYTHONUNBUFFERED", "1");
    cmd.stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    Ok(cmd)
}

impl Backend {
    pub fn state(&self) -> State {
        self.state
            .lock()
            .unwrap_or_else(|p| p.into_inner())
            .clone()
            .unwrap_or(State::Starting)
    }

    fn set(&self, generation: u64, state: State) {
        if *self.generation.lock().unwrap_or_else(|p| p.into_inner()) == generation {
            *self.state.lock().unwrap_or_else(|p| p.into_inner()) = Some(state);
        }
    }

    fn log_tail(&self) -> Vec<String> {
        self.log
            .lock()
            .unwrap_or_else(|p| p.into_inner())
            .iter()
            .cloned()
            .collect()
    }

    /// Ask the backend to go by closing its stdin (it watches for that,
    /// `--watch-stdin`), and kill it only if it is still there after
    /// `STOP_GRACE`. A release build's sidecar is a one-file freeze that
    /// unpacks its runtime to a temporary folder and removes it when its
    /// program exits; killed outright, it leaves the folder behind.
    pub fn stop(&self) {
        if let Some(child) = self.child.lock().unwrap_or_else(|p| p.into_inner()).take() {
            let mut child = child.lock().unwrap_or_else(|p| p.into_inner());
            drop(child.stdin.take());
            let deadline = Instant::now() + STOP_GRACE;
            while Instant::now() < deadline {
                match child.try_wait() {
                    Ok(Some(_)) => return,
                    Ok(None) => thread::sleep(Duration::from_millis(50)),
                    Err(_) => break,
                }
            }
            let _ = child.kill();
            let _ = child.wait();
        }
    }

    /// (Re)start the backend on `library` (None: its default). Returns at
    /// once; poll `state()`.
    pub fn start(self: &Arc<Self>, library: Option<PathBuf>) {
        self.stop();
        let generation = {
            let mut g = self.generation.lock().unwrap_or_else(|p| p.into_inner());
            *g += 1;
            *g
        };
        self.log.lock().unwrap_or_else(|p| p.into_inner()).clear();
        *self.state.lock().unwrap_or_else(|p| p.into_inner()) = Some(State::Starting);

        let mut cmd = match command(library.as_deref()) {
            Ok(c) => c,
            Err(message) => {
                return self.set(
                    generation,
                    State::Error {
                        message,
                        log: vec![],
                    },
                );
            }
        };
        push_log(&self.log, format!("$ {cmd:?}"));
        let mut child = match cmd.spawn() {
            Ok(c) => c,
            Err(e) => {
                let message = format!("could not start the backend: {e}");
                return self.set(
                    generation,
                    State::Error {
                        message,
                        log: self.log_tail(),
                    },
                );
            }
        };
        let stdout = child.stdout.take();
        let stderr = child.stderr.take();
        let child = Arc::new(Mutex::new(child));
        *self.child.lock().unwrap_or_else(|p| p.into_inner()) = Some(child.clone());

        // stderr: kept for the setup screen, echoed for whoever ran us.
        if let Some(err) = stderr {
            let log = self.log.clone();
            thread::spawn(move || {
                for line in lossy_lines(err) {
                    eprintln!("backend: {line}");
                    push_log(&log, line);
                }
            });
        }

        // stdout: the first line is READY; anything after it is just output.
        if let Some(out) = stdout {
            let me = self.clone();
            thread::spawn(move || {
                let mut lines = lossy_lines(out);
                if let Some(first) = lines.next() {
                    match serde_json::from_str::<ReadyLine>(&first) {
                        Ok(r) if r.ready => me.set(
                            generation,
                            State::Ready {
                                port: r.port,
                                token: r.token,
                                library: r.library,
                            },
                        ),
                        _ => {
                            push_log(&me.log, first);
                            me.set(
                                generation,
                                State::Error {
                                    message: "the backend did not report ready".into(),
                                    log: me.log_tail(),
                                },
                            );
                        }
                    }
                }
                for line in lines {
                    println!("backend: {line}");
                    push_log(&me.log, line);
                }
            });
        }

        // Watch it: an exit before READY, or a hang, is an error to show.
        let me = self.clone();
        thread::spawn(move || {
            let started = Instant::now();
            loop {
                thread::sleep(Duration::from_millis(200));
                if *me.generation.lock().unwrap_or_else(|p| p.into_inner()) != generation {
                    return;
                }
                let exited = child
                    .lock()
                    .unwrap_or_else(|p| p.into_inner())
                    .try_wait()
                    .ok()
                    .flatten();
                if let Some(status) = exited {
                    // Let the stderr reader drain before reporting.
                    thread::sleep(Duration::from_millis(150));
                    let message = format!("the backend exited ({status})");
                    me.set(
                        generation,
                        State::Error {
                            message,
                            log: me.log_tail(),
                        },
                    );
                    return;
                }
                if matches!(me.state(), State::Starting) && started.elapsed() > START_TIMEOUT {
                    me.set(
                        generation,
                        State::Error {
                            message: "the backend did not start in time".into(),
                            log: me.log_tail(),
                        },
                    );
                    return;
                }
            }
        });
    }
}
