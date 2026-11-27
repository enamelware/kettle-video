# Releasing Kettle Video

How a set of tested changes becomes a release that users get. Issues are built, merged into `main` and tested one by one on development copies; installed copies never see `main`. They only see GitHub releases, and only the one GitHub marks as the **latest**. The designer decides by hand when a release is made and when it becomes the latest; no script ever does that.

The rule behind this checklist is in `docs/decisions.md` ("Releases go up as pre-releases; the designer marks the latest"), and the flow in `docs/spec.md` ("Releasing").

## Checklist

1. **Ready on main.** Every change meant for this release is merged into `main` and was tested on the devices. `scripts/test.sh full` passes on `main`, and `python3 tools/release_check.py` finds nothing (`docs/dev-environment.md`, "Release check").
2. **CHANGELOG entry.** Add `## <version>` at the top of `CHANGELOG.md`, in plain words for users. It becomes the release's text.
3. **Version bump.** Put the new version in `VERSION`. Commit both on `main` and push.
4. **Tag.** `git tag v<version>`, then `git push origin v<version>`. The tag must be on GitHub before the upload.
5. **Run the release script.** `python3 tools/release.py v<version>`. It builds five files into `dist/` (the archive, its `.sha256`, the release notes, `install.sh` and the one-file installer `install-kettle-video.desktop`), runs the release check on all of them, shows a summary and asks. Read the summary, then type `yes` to upload. Anything else uploads nothing.
   - With the GitHub CLI (`gh`) installed and already signed in, it creates the GitHub release itself: always a **pre-release**, never the latest, with the archive, its `.sha256`, `install.sh` and `install-kettle-video.desktop` attached and the notes as its text.
   - Without a signed-in `gh`, it uploads nothing and prints the same steps for GitHub's website: choose the tag, title `Kettle Video <version>`, paste the notes file's text, attach those four files (not the notes file), tick "Set as a pre-release", leave "Set as the latest release" unticked, publish.
   - The script never asks for, reads or stores a token or password.
6. **Not offered yet.** On a test device with the previous public release installed, open Settings › About › Check for updates: it still says "Up to date" with the previous version.
7. **The update test**, on each test device (Steam Deck with SteamOS, Retroid Pocket Nova with Armada). In Desktop Mode, with the previous public release installed and used (its folders chosen, a film in Continue watching), download the pre-release's `install.sh`, `kettle-video-<version>.tar.gz` and its `.sha256` from the pre-release's page into one folder and run `bash install.sh` there. Then in Gaming Mode: Settings › About shows the new version, the folders and Continue watching are still there, and a film plays. The pre-release's `install-kettle-video.desktop` can't be used for this: it always installs the latest release, which is still the previous one.
8. **One clean install.** On one test device without Kettle Video installed (or after uninstalling it with its data deleted, README "Uninstalling"), install the pre-release with its `install.sh` as in step 7. The first launch is a brand-new onboarding, and the app works in Gaming Mode.
9. **Mark it as the latest.** If all is well: on GitHub's Releases page, edit the pre-release, untick "Set as a pre-release", tick "Set as the latest release", and update it. From now on users are offered it.
10. **Update and restart, once, straight away.** On a test device, open an install of the previous release (keep one back from step 7, or put it back with its own `install.sh`, which asks before installing an older version) and, in Gaming Mode, use Settings › About › Check for updates, then Update and restart. It should restart on the new version with everything kept. **If it fails:** unmark the release as the latest straight away (edit it and tick "Set as a pre-release"; the Releases page should then show the previous release as Latest again, and if not, edit that one and tick "Set as the latest release"), then file a bug.

## What users see

- **While it is a pre-release:** nothing in the app. Check for updates and Update and restart only ever ask GitHub for the latest release, which is never a pre-release or a draft, and there is no switch or setting to include pre-releases. The one-file installer (`install-kettle-video.desktop`) also only ever installs GitHub's latest full release, so a pre-release never reaches it, and the README's "latest release" link goes to the latest release too.
- **But it is public:** the repo is public, so anyone can see a pre-release on the Releases page and download its files by hand. Only the app and the one-file installer ignore it.
- **Once it is marked as the latest:** Check for updates offers it ("Version <version> is available", with What's new and, on an installed copy, Update and restart), the one-file installer installs it, and the README's link leads to it.
- **If it is unmarked again:** the app goes back to offering the previous release; anyone who already updated keeps the new version until the next release.
