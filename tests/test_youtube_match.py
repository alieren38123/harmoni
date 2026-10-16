import json
import os
import subprocess
import unittest
from unittest import mock

# Ensure local imports work when running this file directly.
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in os.sys.path:
    os.sys.path.insert(0, THIS_DIR)

from utils import youtube_match as ym


def cand(vid, duration, title, channel="Someone"):
    return {"id": vid, "duration": duration, "title": title, "channel": channel}


# Real `ytsearch5:"Hozier - Take Me To Church"` results (2026-10).
TAKE_ME_TO_CHURCH = [
    cand("PVjiKRfKpPI", 257, "Hozier - Take Me To Church", "Hozier"),
    cand("SND2LY0s8FE", 242, "Hozier - Take Me To Church (Lyrics)", "Unique Sound"),
    cand("O1wDihZNQyQ", 248, "Hozier performs his hit song 'Take Me To Church' | Later... with Jools Holland - BBC", "BBC"),
    cand("MYSVMgRr6pw", 241, "Hozier - Take Me To Church", "Hozier"),
    cand("1nnRC6jDOCI", 259, "Hozier - Take Me To Church (Pop-Up Show in NYC Subway)", "SubwayCreatures"),
]


class TestPickBest(unittest.TestCase):
    def test_picks_closest_duration_over_top_rank(self):
        best = ym.pick_best(TAKE_ME_TO_CHURCH, 241000, "Take Me To Church", artist="Hozier")
        self.assertEqual(best["id"], "MYSVMgRr6pw")

    def test_near_equal_lengths_prefer_artist_channel(self):
        # Spotify says 241.688s: the lyric re-upload (242s) is closer than
        # Hozier's own upload (241s), but both are within 2s.
        best = ym.pick_best(TAKE_ME_TO_CHURCH, 241688, "Take Me To Church", artist="Hozier")
        self.assertEqual(best["id"], "MYSVMgRr6pw")

    def test_topic_channel_counts_as_artist(self):
        cands = [cand("reup", 200, "Song"), cand("topic", 201, "Song", "Radiohead - Topic")]
        self.assertEqual(ym.pick_best(cands, 200000, "Song", artist="Radiohead, Someone Else")["id"], "topic")

    def test_clearly_closer_length_beats_artist_channel(self):
        cands = [cand("own", 209, "Song", "Hozier"), cand("reup", 200, "Song")]
        self.assertEqual(ym.pick_best(cands, 200000, "Song", artist="Hozier")["id"], "reup")

    def test_duration_ms_may_be_a_string(self):
        # Exportify CSV rows carry "Duration (ms)" as text.
        best = ym.pick_best(TAKE_ME_TO_CHURCH, "241000", "Take Me To Church", artist="Hozier")
        self.assertEqual(best["id"], "MYSVMgRr6pw")

    def test_rejects_variant_titles_unless_requested(self):
        cands = [cand("live", 221, "Song (Live at Wembley)"), cand("far", 260, "Song")]
        self.assertIsNone(ym.pick_best(cands, 221000, "Song"))
        self.assertEqual(ym.pick_best(cands, 221000, "Song - Live at Wembley")["id"], "live")

    def test_variant_words_match_whole_words_only(self):
        # "Alive" must not count as "live", nor "Recover" as "cover".
        cands = [cand("a", 200, "Alive"), cand("b", 200, "Recover")]
        self.assertEqual(ym.pick_best(cands, 200000, "Alive")["id"], "a")
        self.assertEqual(ym.pick_best(cands[1:], 200000, "Recover")["id"], "b")

    def test_tie_goes_to_higher_ranked_result(self):
        cands = [cand("first", 222, "Song"), cand("second", 220, "Song")]
        self.assertEqual(ym.pick_best(cands, 221000, "Song")["id"], "first")

    def test_none_when_outside_tolerance_or_unknown(self):
        self.assertIsNone(ym.pick_best([cand("x", 300, "Song")], 200000, "Song"))
        self.assertIsNone(ym.pick_best(TAKE_ME_TO_CHURCH, None, "Take Me To Church"))
        self.assertIsNone(ym.pick_best([cand("x", None, "Song")], 200000, "Song"))


class TestStripEdition(unittest.TestCase):
    def test_strips_common_edition_suffixes(self):
        self.assertEqual(ym.strip_edition("Hozier (Special Edition)"), "Hozier")
        self.assertEqual(ym.strip_edition("OK Computer OKNOTOK 1997 2017"), "OK Computer OKNOTOK 1997 2017")
        self.assertEqual(ym.strip_edition("Abbey Road (Remastered 2009)"), "Abbey Road")
        self.assertEqual(ym.strip_edition("Rumours - 2004 Remaster"), "Rumours")
        self.assertEqual(ym.strip_edition("Folklore [Deluxe Version]"), "Folklore")
        self.assertEqual(ym.strip_edition("Wellerman - The Album"), "Wellerman - The Album")


def fake_run(results_by_query):
    """subprocess.run stand-in returning yt-dlp -J output per search query."""

    def run(cmd, **kwargs):
        search = next(a for a in cmd if a.startswith("ytsearch"))
        query = search.split(":", 1)[1]
        entries = results_by_query.get(query)
        if entries is None:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"entries": entries}), stderr="")

    return run


class TestResolveTarget(unittest.TestCase):
    TRACK = {"artist": "Hozier", "track": "Take Me To Church", "duration_ms": 241000, "album": "Hozier (Special Edition)"}

    def test_returns_url_of_best_match(self):
        with mock.patch.object(ym.subprocess, "run", side_effect=fake_run({"Hozier - Take Me To Church": TAKE_ME_TO_CHURCH})) as run:
            target = ym.resolve_target("Hozier", "Take Me To Church", self.TRACK, {})
        self.assertEqual(target, "https://www.youtube.com/watch?v=MYSVMgRr6pw")
        cmd = run.call_args.args[0]
        self.assertIn("ytsearch5:Hozier - Take Me To Church", cmd)
        self.assertIn("--flat-playlist", cmd)

    def test_passes_extra_ytdlp_args_to_search(self):
        cfg = {"ytdlp_extra_args": "--cookies c.txt"}
        with mock.patch.object(ym.subprocess, "run", side_effect=fake_run({"Hozier - Take Me To Church": TAKE_ME_TO_CHURCH})) as run:
            ym.resolve_target("Hozier", "Take Me To Church", self.TRACK, cfg)
        self.assertIn("--cookies", run.call_args.args[0])

    def test_falls_back_to_album_query_then_ytsearch1(self):
        far = [cand("far", 400, "Hozier - Take Me To Church")]
        album_hit = [cand("topic", 240, "Take Me To Church")]
        with mock.patch.object(ym.subprocess, "run", side_effect=fake_run({
            "Hozier - Take Me To Church": far,
            "Hozier - Take Me To Church Hozier": album_hit,
        })) as run:
            target = ym.resolve_target("Hozier", "Take Me To Church", self.TRACK, {})
        self.assertEqual(target, "https://www.youtube.com/watch?v=topic")
        self.assertEqual(run.call_count, 2)

        with mock.patch.object(ym.subprocess, "run", side_effect=fake_run({"Hozier - Take Me To Church": far})):
            target = ym.resolve_target("Hozier", "Take Me To Church", self.TRACK, {})
        self.assertEqual(target, "ytsearch1:Hozier - Take Me To Church")

    def test_no_search_without_duration_or_when_disabled(self):
        with mock.patch.object(ym.subprocess, "run") as run:
            no_duration = {**self.TRACK, "duration_ms": None}
            self.assertEqual(ym.resolve_target("Hozier", "Take Me To Church", no_duration, {}), "ytsearch1:Hozier - Take Me To Church")
            disabled = {"youtube_search_candidates": 1}
            self.assertEqual(ym.resolve_target("Hozier", "Take Me To Church", self.TRACK, disabled), "ytsearch1:Hozier - Take Me To Church")
            self.assertEqual(ym.resolve_target("Hozier", "Take Me To Church", None, {}), "ytsearch1:Hozier - Take Me To Church")
        run.assert_not_called()

    def test_search_errors_fall_back(self):
        with mock.patch.object(ym.subprocess, "run", side_effect=OSError("yt-dlp missing")):
            target = ym.resolve_target("Hozier", "Take Me To Church", self.TRACK, {})
        self.assertEqual(target, "ytsearch1:Hozier - Take Me To Church")


if __name__ == "__main__":
    unittest.main()
