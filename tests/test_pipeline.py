"""Regression coverage for loopback devices that stop sending silence frames."""

import unittest
from unittest.mock import Mock, patch

from src.config import Config
from src.core.pipeline import Pipeline


class PipelineIdleTests(unittest.TestCase):
    def make_pipeline(self):
        with patch("src.core.pipeline.ThreadPoolExecutor"):
            pipeline = Pipeline(Config({"audio": {"silence_timeout_ms": 700}}), Mock())
        pipeline.capture = Mock()
        pipeline.capture.read.return_value = b""
        pipeline.vad = Mock()
        pipeline._stop = Mock()
        return pipeline

    def test_playback_end_submits_unfinished_speech_once(self):
        pipeline = self.make_pipeline()
        utterance = object()
        pipeline.vad.flush_final.side_effect = [utterance, None]
        pipeline._stop.is_set.side_effect = [False, False, True]
        with patch("src.core.pipeline.time.monotonic", side_effect=[0, 1, 2]):
            pipeline._run()
        pipeline._exec.submit.assert_called_once_with(pipeline._transcribe, utterance)

    def test_short_gap_does_not_split_speech(self):
        pipeline = self.make_pipeline()
        pipeline._stop.is_set.side_effect = [False, True]
        with patch("src.core.pipeline.time.monotonic", side_effect=[0, 0.1]):
            pipeline._run()
        pipeline.vad.flush_final.assert_not_called()
        pipeline._exec.submit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
