# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- **Album search in the Spotify tab**: Search the Spotify catalog for albums from the GUI and load or download them like playlists. Results are queued as `Artist - Album`.

- **Length-matched YouTube search**: When a track's length is known (Spotify, Exportify CSV), downloads compare the top `youtube_search_candidates` (default 5) YouTube results and pick the one within 10s of it, skipping live/remix/cover/sped-up variants unless the track title asks for one and preferring the artist's own channel. If nothing matches, it retries once with the album name (edition suffixes stripped), then falls back to the top result as before. Applies to GUI and CLI downloads. Set `youtube_search_candidates` to `1` for the old behavior.

### Fixed
- **Tracks from one Spotify album were tagged as different albums**: the GUI queue only kept artist/title, so each file got its own MusicBrainz guess (often a single or EP) and taggers like beets split the album apart. Queue items now carry the Spotify track dict, and files are tagged with album, album artist, track number (`n/total`) and disc number for every template (MP3, M4A, FLAC, Ogg/Opus, AAC, WAV). With the album known, the per-track MusicBrainz guess no longer runs. Spotify playlists and Liked Songs share the same normalizer, which also restores skipping nameless artists.
- **Playlist track counts missing in the Spotify tab**: Spotify now reports a playlist's track count under `items` instead of `tracks`; both the GUI worker and `SpotifyDataLoader` read the new field (with fallback).

### Notes
- Playlist search was deliberately left out: Spotify blocks development-mode apps from reading tracks of playlists the user doesn't own or collaborate on (`403 Forbidden`), so results would be dead ends.

## [1.2.0] - 2026-07-30

### Added
- **Custom yt-dlp / ffmpeg arguments**: You can now pass extra CLI flags straight through to yt-dlp and ffmpeg for every download:
  - New `ytdlp_extra_args` and `ffmpeg_extra_args` config fields (ffmpeg args are forwarded via yt-dlp's `--postprocessor-args`)
  - New "Extra yt-dlp arguments" / "Extra ffmpeg arguments" fields in the GUI Settings view, under Download Settings
  - Editable from the CLI config menu like any other setting
  - Applied consistently across all download paths: track/batch downloads, retries, and direct link/playlist downloads
- **Disconnect button for Spotify**: The Spotify view now has a "Disconnect" button next to Connect, so you can clear the cached token and re-auth without digging through files.

### Fixed
- **Duplicate-detection and metadata matching for special/reserved characters**: Filenames with characters yt-dlp sanitizes (`: * / \ < > | " ?`) or full-width unicode variants no longer cause tracks to be re-downloaded or fail metadata embedding. Matching is now done via a normalized key (`utils/filename_match.py`) instead of exact/prefix string comparison, in `downloader/metadata.py` and `utils/track_checker.py`.
- **Bundled yt-dlp binary was being stripped on macOS/Linux builds**, breaking every download on those platforms. The build workflow and `build-macos.sh` no longer strip it.

### Why
- Passing custom flags was the most requested missing feature: without something like `--cookies cookies.txt`, large playlist downloads get rate-limited/timed out by YouTube. Power users can now also tweak ffmpeg output (e.g. sample rate) without touching code.
- The filename-matching fix prevents silent re-downloads/duplicate work for tracks whose titles contain characters that get sanitized differently across yt-dlp versions/platforms.
- The macOS/Linux build fix was a release blocker — every download failed post-build until yt-dlp was no longer stripped.

### Compatibility
- Fully backward compatible with older `config.json` files. Missing keys are backfilled with empty defaults on load, so existing configs keep working unchanged and no extra arguments are applied unless explicitly set.

## [1.1.0] - 2026-03-03

### Added
- **yt-dlp Update Checker & Installer**: Implemented a comprehensive update system for yt-dlp with:
  - Automatic update detection through the update checker module
  - In-app notifications to alert users when updates are available
  - One-click installer for seamless yt-dlp updates
  - New `ytdlp_updater.py` worker module handling update logic in GUI thread

### Changed
- **Settings View**: Now automatically reloads configuration on save and updates the UI to reflect changes immediately
- **Spotify Integration**: Refactored token expiration checking to use the TokenManager, improving code maintainability and centralizing token lifecycle management
- **Main Window**: Updated to support the new yt-dlp update checker integration

### Why
These changes were made to improve user experience and code quality:
1. Users can now keep yt-dlp updated without manual intervention, ensuring access to the latest features and bug fixes
2. Settings changes take immediate effect without requiring app restart (I think you'll have to reload the app after installing yt-dlp because visually it shows not installed)
3. Centralized token management through TokenManager reduces duplication and potential bugs in token handling across different parts of the application
4. when you open the app, there will be some quick cli openings which is a bit scary but don't worry, it's just small scripts to check for things if they are there or not.

## [1.0.0] - 2026-01-01

### Added
- Initial stable release of Harmoni
- GUI version 1.0.0 with core features
- Initial yt-dlp update checker foundation
