"""Spotify API worker thread for fetching playlists and tracks."""

from typing import List, Optional
from PySide6.QtCore import QThread, Signal

from spotify_api.auth import SpotifyPKCEAuth
from spotify_api.client import SpotifyClient
from spotify_api.data_loader import SpotifyDataLoader
from spotify_api.token_manager import TokenManager


class SpotifyWorker(QThread):
    """
    Worker thread for Spotify API operations.

    Signals:
        playlists_loaded: Emitted when playlists are loaded
        tracks_loaded: Emitted when tracks are loaded
        liked_songs_loaded: Emitted when liked songs are loaded
        albums_found: Emitted with album search results
        error: Emitted on error
        progress: Emitted during long operations
    """

    playlists_loaded = Signal(list)  # List of playlist dicts
    tracks_loaded = Signal(str, list)  # playlist_id, list of track dicts
    tracks_batch = Signal(str, list)  # playlist_id, batch of tracks (streaming)
    liked_songs_loaded = Signal(list)  # List of track dicts
    albums_found = Signal(list)  # List of album dicts (see SpotifyDataLoader.search_albums)
    error = Signal(str)  # Error message
    progress = Signal(str, int, int)  # message, current, total

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.config = config
        self._task = None
        self._task_args = {}
        self._cancelled = False

    def fetch_playlists(self):
        """Queue task to fetch user playlists."""
        self._task = "playlists"
        self._task_args = {}
        self.start()

    def fetch_playlist_tracks(self, playlist_id: str, playlist_name: str = ""):
        """Queue task to fetch tracks from a playlist."""
        self._task = "playlist_tracks"
        self._task_args = {"playlist_id": playlist_id, "playlist_name": playlist_name}
        self.start()

    def fetch_liked_songs(self):
        """Queue task to fetch user's liked songs."""
        self._task = "liked_songs"
        self._task_args = {}
        self.start()

    def search_albums(self, query: str):
        """Queue task to search the Spotify catalog for albums."""
        self._task = "search_albums"
        self._task_args = {"query": query}
        self.start()

    def fetch_album_tracks(self, album: dict):
        """Queue task to fetch tracks from an album (a search_albums result)."""
        self._task = "album_tracks"
        self._task_args = {"album": album}
        self.start()

    def run(self):
        """Execute the queued task."""
        self._cancelled = False

        try:
            # Get access token
            auth = SpotifyPKCEAuth(self.config)
            token_info = auth.load_cached_token()

            if not token_info or not token_info.access_token:
                self.error.emit("Not connected to Spotify. Please log in first.")
                return

            # Check if token needs refresh
            if TokenManager.is_expired(token_info):
                if token_info.refresh_token:
                    try:
                        token_info = auth.refresh_access_token(
                            refresh_token=token_info.refresh_token
                        )
                    except Exception as e:
                        self.error.emit(f"Failed to refresh token: {e}")
                        return
                else:
                    self.error.emit("Token expired. Please log in again.")
                    return

            # Create Spotify client
            client = SpotifyClient(self.config)
            client.set_token(token_info)

            # Execute task
            if self._task == "playlists":
                self._fetch_playlists(client)
            elif self._task == "playlist_tracks":
                self._fetch_playlist_tracks(client)
            elif self._task == "liked_songs":
                self._fetch_liked_songs(client)
            elif self._task == "search_albums":
                self._search_albums(client)
            elif self._task == "album_tracks":
                self._fetch_album_tracks(client)

        except Exception as e:
            if not self._cancelled:
                self.error.emit(str(e))

    def _fetch_playlists(self, client: SpotifyClient):
        """Fetch all user playlists."""
        self.progress.emit("Fetching playlists...", 0, 0)

        playlists = []
        offset = 0
        limit = 50

        while not self._cancelled:
            result = client.current_user_playlists(limit=limit, offset=offset)
            items = result.get("items", [])

            for item in items:
                playlist = {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "owner": item.get("owner", {}).get("display_name", "Unknown"),
                    # Spotify now reports the count under "items" (formerly "tracks").
                    "tracks_total": (item.get("items") or item.get("tracks") or {}).get("total", 0),
                    "image_url": item.get("images", [{}])[0].get("url") if item.get("images") else None,
                }
                playlists.append(playlist)

            total = result.get("total", 0)
            self.progress.emit(f"Loaded {len(playlists)} of {total} playlists", len(playlists), total)

            if result.get("next"):
                offset += limit
            else:
                break

        if not self._cancelled:
            self.playlists_loaded.emit(playlists)

    def _fetch_playlist_tracks(self, client: SpotifyClient):
        """Fetch tracks from a specific playlist."""
        playlist_id = self._task_args.get("playlist_id")
        playlist_name = self._task_args.get("playlist_name", "")

        self.progress.emit(f"Fetching tracks from {playlist_name}...", 0, 0)

        tracks = []
        offset = 0
        limit = 100

        while not self._cancelled:
            result = client.playlist_items(playlist_id, limit=limit, offset=offset)
            items = result.get("items", [])

            batch = []
            for item in items:
                track_obj = item.get("item") or item.get("track")
                if not track_obj:
                    continue

                # Skip local files and unavailable tracks
                if track_obj.get("is_local") or not track_obj.get("id"):
                    continue

                artists = [a.get("name", "") for a in track_obj.get("artists", [])]
                track = {
                    "artist": ", ".join(artists) if artists else "Unknown Artist",
                    "track": track_obj.get("name", "Unknown Track"),
                    "album": track_obj.get("album", {}).get("name", ""),
                    "duration_ms": track_obj.get("duration_ms", 0),
                    "spotify_id": track_obj.get("id"),
                }
                tracks.append(track)
                batch.append(track)

            if batch and not self._cancelled:
                self.tracks_batch.emit(playlist_id, batch)

            total = result.get("total", 0)
            self.progress.emit(
                f"Loaded {len(tracks)} of {total} tracks from {playlist_name}",
                len(tracks),
                total
            )

            if result.get("next"):
                offset += limit
            else:
                break

        if not self._cancelled:
            self.tracks_loaded.emit(playlist_id, tracks)

    def _fetch_liked_songs(self, client: SpotifyClient):
        """Fetch user's liked songs."""
        self.progress.emit("Fetching liked songs...", 0, 0)

        tracks = []
        offset = 0
        limit = 50

        while not self._cancelled:
            result = client.current_user_saved_tracks(limit=limit, offset=offset)
            items = result.get("items", [])

            batch = []
            for item in items:
                track_obj = item.get("track")
                if not track_obj:
                    continue

                # Skip local files
                if track_obj.get("is_local") or not track_obj.get("id"):
                    continue

                artists = [a.get("name", "") for a in track_obj.get("artists", [])]
                track = {
                    "artist": ", ".join(artists) if artists else "Unknown Artist",
                    "track": track_obj.get("name", "Unknown Track"),
                    "album": track_obj.get("album", {}).get("name", ""),
                    "duration_ms": track_obj.get("duration_ms", 0),
                    "spotify_id": track_obj.get("id"),
                }
                tracks.append(track)
                batch.append(track)

            if batch and not self._cancelled:
                self.tracks_batch.emit("__liked_songs__", batch)

            total = result.get("total", 0)
            self.progress.emit(f"Loaded {len(tracks)} of {total} liked songs", len(tracks), total)

            if result.get("next"):
                offset += limit
            else:
                break

        if not self._cancelled:
            self.liked_songs_loaded.emit(tracks)

    def _search_albums(self, client: SpotifyClient):
        """Search the catalog for albums."""
        query = self._task_args.get("query", "")
        self.progress.emit(f"Searching albums for \"{query}\"...", 0, 0)
        albums = SpotifyDataLoader(client).search_albums(query)
        if not self._cancelled:
            self.albums_found.emit(albums)

    def _fetch_album_tracks(self, client: SpotifyClient):
        """Fetch tracks from an album, reusing the playlist track signals."""
        album = self._task_args.get("album") or {}
        album_id = album.get("id")
        self.progress.emit(f"Fetching tracks from {album.get('name', '')}...", 0, 0)
        tracks = SpotifyDataLoader(client).load_album_tracks(album)
        if self._cancelled:
            return
        if tracks:
            self.tracks_batch.emit(album_id, tracks)
        self.tracks_loaded.emit(album_id, tracks)

    def cancel(self):
        """Cancel the current operation."""
        self._cancelled = True
