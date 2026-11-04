import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from leadgen.collectors import validate_job
from leadgen.model import normalize
from leadgen.store import Store
from leadgen.worker import run


def record(item_id):
    return normalize({"source": "2gis", "source_id": item_id, "name": "Компания " + item_id,
                      "city": "Москва", "address": "Ленина, " + item_id})


class WorkerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "leads.sqlite3")
        self.job_id = self.store.create_job(validate_job({"source": "2gis", "city": "moscow", "query": "кафе", "limit": 2}))

    def test_limit_applies_to_persisted_results_even_if_page_returns_more(self):
        def collect(config, emit, checkpoint, seen):
            for item_id in ("1", "2", "3"):
                emit(record(item_id))
        with patch("leadgen.worker.collect", collect):
            self.assertEqual(run(self.tmp.name, self.job_id), 0)
        self.assertEqual(len(self.store.companies()), 2)
        self.assertEqual(self.store.jobs()[0]["count"], 2)

    def test_stop_and_resume_preserve_count_and_previous_ids(self):
        def interrupted(config, emit, checkpoint, seen):
            emit(record("1"))
            raise KeyboardInterrupt
        with patch("leadgen.worker.collect", interrupted):
            self.assertEqual(run(self.tmp.name, self.job_id), 130)
        self.assertEqual(self.store.jobs()[0]["status"], "stopped")

        def resume(config, emit, checkpoint, seen):
            self.assertIn(("2gis", "1"), seen)
            emit(record("2"))
        with patch("leadgen.worker.collect", resume):
            self.assertEqual(run(self.tmp.name, self.job_id), 0)
        job = self.store.jobs()[0]
        self.assertEqual((job["status"], job["count"]), ("done", 2))


if __name__ == "__main__":
    unittest.main()
