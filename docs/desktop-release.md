# Windows Desktop Release

InternTrack desktop releases are built from immutable tags and published as draft GitHub Releases. Pull-request installers remain intentionally unsigned test artifacts; the release workflow refuses to publish when signing material is missing.

## One-time setup

Acquire a Windows code-signing certificate from a trusted certificate authority. Store its exported PFX and password outside the repository. Generate a separate Tauri updater keypair and keep durable offline copies of both private credentials.

Configure these GitHub Actions repository secrets:

| Secret | Purpose |
| --- | --- |
| `WINDOWS_CERTIFICATE_PFX_BASE64` | Base64-encoded PFX containing the Windows code-signing certificate and private key |
| `WINDOWS_CERTIFICATE_PASSWORD` | PFX export password |
| `WINDOWS_TIMESTAMP_URL` | RFC 3161 timestamp URL supplied by the certificate authority |
| `TAURI_SIGNING_PRIVATE_KEY` | Private key used only to sign Tauri updater bundles |
| `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` | Optional password for the Tauri updater private key |

Never add a PFX, updater private key, password, generated release config, or secret value to the repository. The updater private key must be backed up securely: installed clients cannot accept later updates if it is lost and replaced without a planned key rotation.

## Prepare a release

1. Update the version in `app/version.py`, `desktop/src-tauri/tauri.conf.json`, `desktop/src-tauri/Cargo.toml`, and `desktop/package.json`.
2. Run `./desktop/scripts/validate_release_version.ps1` and complete the normal pull-request review.
3. Merge the reviewed stack in order.
4. Create and push the exact tag `desktop-v<version>`, for example `desktop-v0.2.0`.

The tag starts the **Desktop Release** workflow. It verifies the tag/version match, imports the certificate into the ephemeral Windows runner, builds the Python sidecar, signs the executable and NSIS installer, verifies Authenticode, creates Tauri updater artifacts and signatures, writes `SHA256SUMS.txt`, and uploads everything to a draft GitHub Release.

## Release review

Both desktop workflows first run the CI-only silent installer check. It installs into a generated RUNNER_TEMP directory, exercises the installed API plus migration and reversible recovery fixtures, and drives the installed WebView2 window through startup failures, Retry, and process cleanup before uninstalling. Window screenshots and driver logs are retained for 14 days in a separate diagnostics artifact, including on failures. The helpers accept only GitHub-hosted Windows runners. See [NSIS command-line options](https://nsis.sourceforge.io/Docs/Chapter3.html) and [GitHub runner variables](https://docs.github.com/en/actions/reference/workflows-and-actions/variables) for the installation flags and host checks.

Before publishing the draft:

1. Download the release artifact on a clean Windows machine.
2. Verify the Authenticode signer and SHA-256 checksum.
3. Install, launch, sign in, create an application, restart, and exercise backup recovery.
4. Confirm the updater bundle and `.sig` file are attached.
5. Review generated notes and publish only after the smoke test passes.

The application does not check for remote updates yet. Signed updater artifacts are generated now so a later updater client can be introduced without changing the release trust boundary.

## Current candidate

The current candidate is `0.2.0-rc.4`. See [release-candidate.md](release-candidate.md) for integration decisions, automated packaging checks, candidate download instructions, and the pending manual release gates.

