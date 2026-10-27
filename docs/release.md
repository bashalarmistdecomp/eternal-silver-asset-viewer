# Releases

A release is the app's installers for each system, made from a tagged
commit of `main`:

| system | what | made on |
|---|---|---|
| Windows | `…_x64-setup.exe` (NSIS), `…_x64_en-US.msi` | `windows-latest` |
| macOS, Apple silicon | `…_aarch64.dmg` | `macos-14` |
| macOS, Intel | `…_x64.dmg` | `macos-15-intel` |
| Linux | `….AppImage`, `….deb`, `….rpm` | `ubuntu-22.04` |

Each carries the frozen backend (no Python needed), `LICENSE`, `NOTICE.md`
and its system's `THIRD-PARTY-NOTICES.txt`. The owner's rulings
(2026-10-27): the builds are made by GitHub Actions; they are **not
signed**, and the README says how to open them; the public history starts
at one commit; the first release ships what works, its known issues named
in its notes.

## How a build is made

`.github/workflows/build.yml`, on each system, for every push to `main`,
every pull request and every tag `v<version>`:

1. the checks (docs/development.md, "Checks"): the backend's tests (the disc tests skip,
   no library there), the tools' tests, the page's type check and build,
   Clippy; on Linux the lints too, and on a pull request the version check;
2. `npm run bundle`: the backend frozen (`app/scripts/build-sidecar.mjs`),
   the notices written (`tools/notices.py`, which fails the build on a
   package whose licence would not let the app stay MIT), the installers;
3. `tools/smoke.py` runs the frozen backend once as the app does: what
   PyInstaller left out shows only when it runs;
4. the installers and notices kept as the run's artifacts.

On a tag, a last job puts every system's installers and notices in a
**draft** release on GitHub.

The same runs on one machine: `cd app && npm run bundle`, then
`python3 tools/smoke.py app/src-tauri/binaries/eternal-silver-asset-viewer-backend-*`.

## The first time (the owner's)

1. **The history.** The public repository starts at one commit: `main`
   is that commit, and the history before it is kept on the owner's
   machine only, on the branches `history/pre-public` (up to 0.2.1) and
   `history/pre-public-2` (from 0.2.1 on). Never push them, or any branch
   made before them: push `main` and tags by name.
2. **The repository.** Make it on GitHub (private until the release is
   published), then, in the checkout:

   ```sh
   git remote add origin <the repository's URL>
   git push -u origin main
   ```

3. **The first build.** That push starts the workflow. Its first run on
   Windows and macOS is the first time the app is built or tested there,
   so expect fixes; each is a commit to `main` like any other.

## Making a release

1. **The version.** `main`'s version moved with the work (docs/development.md,
   "Versions"). A minor step for the release is the owner's word:
   `python3 tools/versions.py --set 0.3.0`, committed.
2. **The tag.** `git tag v0.3.0 && git push origin v0.3.0`. The workflow
   builds every system and makes the draft release.
3. **The notes.** In the draft: what is new; the known issues; how to
   open an unsigned app (the README's "Installing it").
4. **Before publishing**, on each system (a machine or a virtual one):
   install it, add a disc, open the game, play a song and a movie, export
   something; on macOS and Windows, the unsigned prompts as the README
   says. Check that the tagged tree holds nothing copied off a game disc:
   no bytes, no text.
5. **Publishing** the draft is the owner's, by hand.

The first time the repository is made public, protect `main`: **Settings →
Rules → Rulesets**, a ruleset on `main` that blocks force pushes and
deletion. A private repository on GitHub's free plan cannot have one; until
then the pre-push hook (docs/development.md, "The hooks") is the guard.

## Not done

- **Signing.** macOS needs an Apple Developer ID (and notarization) and
  Windows a code-signing certificate; with them the prompts go. The Mac
  bundle is signed ad hoc (`"signingIdentity": "-"`), which makes macOS
  offer "Open Anyway" rather than call the app damaged.
- **Updates.** The app does not look for a newer release.
