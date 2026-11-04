import io
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from urllib.error import HTTPError, URLError
from unittest.mock import patch

from leadgen.collectors import validate_job
from leadgen.crm import EspoClient, sync
from leadgen.importers import import_2gis
from leadgen.dgis import add_catalog_dates
from leadgen.model import normalize, website
from leadgen.store import Store


def company(**changes):
    return normalize({"source": "yandex", "source_id": "101", "name": "Клиника", "city": "Москва",
                      "address": "Ленина, 1", "phone": "8 (999) 123-45-67",
                      "site": "https://clinic.ru/?utm_source=maps", **changes})


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "test.sqlite3")

    def test_same_source_and_cross_source_merge_but_branches_stay_separate(self):
        first = self.store.ingest(company())
        self.assertEqual(first, self.store.ingest(company()))
        second = self.store.ingest(company(source="2gis", source_id="201", email="contact@clinic.ru"))
        self.assertEqual(first, second)
        self.store.ingest(company(source_id="102", address="Ленина, 2"))
        rows = self.store.companies()
        self.assertEqual(len(rows), 2)
        data = next(r["data"] for r in rows if r["id"] == first)
        self.assertEqual(len(data["sources"]), 2)
        self.assertEqual(data["emails"], ["contact@clinic.ru"])
        self.assertEqual(data["phones"], ["+79991234567"])

    def test_queue_survives_restart_and_unchanged_record_does_not_resync(self):
        item_id = self.store.ingest(company())
        row = self.store.companies(True)[0]
        self.store.synced(item_id, row["revision"], "crm-1")
        self.store.ingest(company())
        reopened = Store(self.store.path)
        self.assertEqual(reopened.companies(True), [])
        reopened.ingest(company(email="new@clinic.ru"))
        self.assertEqual(len(reopened.companies(True)), 1)

    def test_partial_card_does_not_erase_previous_contacts(self):
        self.store.ingest(company(email="contact@clinic.ru"))
        self.store.ingest(company(phone="", site="", email=""))
        data = self.store.companies()[0]["data"]
        self.assertEqual(data["website_status"], "Present")
        self.assertEqual(data["phones"], ["+79991234567"])

    def test_ack_of_old_revision_leaves_new_observation_pending(self):
        item_id = self.store.ingest(company())
        old_revision = self.store.companies(True)[0]["revision"]
        self.store.ingest(company(email="new@clinic.ru"))
        self.store.synced(item_id, old_revision, "crm-1")
        self.assertEqual(len(self.store.companies(True)), 1)

    def test_job_progress_survives_restart(self):
        job_id = self.store.create_job(validate_job({"source": "yandex", "city": "Москва", "query": "кафе"}))
        self.store.ingest(company(), job_id)
        self.store.ingest(company(), job_id)
        self.assertEqual(len(Store(self.store.path).job_records(job_id)), 1)

    def test_common_address_spellings_match_without_merging_house_numbers(self):
        item_id = self.store.ingest(company(address="Россия, Москва, улица Ленина, д. 1/2"))
        self.assertEqual(item_id, self.store.ingest(company(source="2gis", source_id="22", address="ул. Ленина, 1/2")))
        self.store.ingest(company(source="2gis", source_id="23", address="ул. Ленина, 12"))
        self.assertEqual(len(self.store.companies()), 2)

    def test_catalog_date_enrichment_is_retained_on_later_partial_observation(self):
        item_id = self.store.ingest(normalize({"source": "2gis", "source_id": "42", "name": "Клиника"}))
        self.store.ingest(normalize({"source": "2gis", "source_id": "42", "name": "Клиника",
                                     "gis_created_at": "2024-04-05T00:00:00+03:00"}))
        self.store.ingest(normalize({"source": "2gis", "source_id": "42", "name": "Клиника"}))
        row = next(r for r in self.store.companies() if r["id"] == item_id)
        self.assertEqual(row["data"]["gis_created_at"], "2024-04-05T00:00:00+03:00")

    def test_ratings_are_kept_per_source_and_partial_updates_preserve_them(self):
        company_id = self.store.ingest(company(rating=4.7, reviews=81))
        self.store.ingest(company(source="2gis", source_id="201", rating=4.2, reviews=19))
        self.store.ingest(company(rating=None, reviews=None))
        data = next(row["data"] for row in self.store.companies() if row["id"] == company_id)
        self.assertEqual(data["source_metrics"]["yandex"], {"rating": 4.7, "review_count": 81})
        self.assertEqual(data["source_metrics"]["2gis"], {"rating": 4.2, "review_count": 19})

    def test_startup_migration_canonicalizes_legacy_domains(self):
        company_id = self.store.ingest(company(site="https://clinic.ru"))
        with self.store.connect() as db:
            record = json.loads(db.execute("SELECT data FROM observations WHERE source_id='101'").fetchone()[0])
            record["websites"] = ["http://пример.рф/"]
            db.execute("UPDATE observations SET data=? WHERE source='yandex' AND source_id='101'",
                       (json.dumps(record, ensure_ascii=False),))
            row = db.execute("SELECT data FROM companies WHERE id=?", (company_id,)).fetchone()
            data = json.loads(row[0])
            data["websites"] = ["http://пример.рф/"]
            db.execute("UPDATE companies SET data=? WHERE id=?", (json.dumps(data, ensure_ascii=False), company_id))
        migrated = Store(self.store.path)
        self.assertEqual(migrated.companies()[0]["data"]["websites"], ["http://xn--e1afmkfd.xn--p1ai/"])


class NormalizeTest(unittest.TestCase):
    def test_social_is_not_a_company_website(self):
        item = company(site="https://vk.com/clinic")
        self.assertEqual(item["website_status"], "NotListed")
        self.assertEqual(item["social"], ["https://vk.com/clinic"])

    def test_tracking_parameters_removed_but_business_query_kept(self):
        self.assertEqual(website("clinic.ru/?branch=12&utm_source=maps&yclid=1"), "https://clinic.ru/?branch=12")
        self.assertEqual(website("javascript:alert(1)"), "")

    def test_international_domains_are_converted_to_ascii_for_crm(self):
        self.assertEqual(website("http://пример.рф/"), "http://xn--e1afmkfd.xn--p1ai/")

    def test_2gis_keeps_all_contacts_and_stable_id(self):
        record = {"id": "555_random", "type": "branch", "name": "Клиника", "contact_groups": [
            {"contacts": [{"type": "phone", "value": "89991234567", "url": "tel:89991234567"},
                          {"type": "phone", "value": "89991234568"},
                          {"type": "email", "value": "hello@clinic.ru", "url": "mailto:hello@clinic.ru"},
                          {"type": "website", "value": "clinic.ru"}]}]}
        item = list(import_2gis(record))[0]
        self.assertEqual(item["source_id"], "555")
        self.assertEqual(len(item["phones"]), 2)
        self.assertEqual(item["emails"], ["hello@clinic.ru"])
        self.assertEqual(item["website_status"], "Present")

    def test_2gis_catalog_date_survives_normalization(self):
        item = normalize({"source": "2gis", "source_id": "555", "name": "Клиника",
                          "gis_created_at": "2025-02-03T12:00:00+03:00"})
        self.assertEqual(item["gis_created_at"], "2025-02-03T12:00:00+03:00")


class DgisApiTest(unittest.TestCase):
    def test_enriches_in_batches_of_100(self):
        from contextlib import closing
        calls = []

        def opener(request, timeout):
            query = parse_qs(urlsplit(request.full_url).query)
            ids = query["id"][0].split(",")
            calls.append(ids)
            payload = {"meta": {"code": 200}, "result": {"items": [
                {"id": item_id + "_stats", "dates": {"created_at": "2025-01-01T00:00:00+03:00"}}
                for item_id in ids
            ]}}
            return closing(io.BytesIO(json.dumps(payload).encode()))

        records = [{"source": "2gis", "source_id": str(i), "name": f"Company {i}"} for i in range(205)]
        result = add_catalog_dates(records, "secret-test-key", opener)
        self.assertEqual([len(batch) for batch in calls], [100, 100, 5])
        self.assertEqual(len(result), 205)
        self.assertEqual(result[-1]["gis_created_at"], "2025-01-01T00:00:00+03:00")

    def test_api_errors_are_reported_without_leaking_key(self):
        from contextlib import closing

        def opener(request, timeout):
            return closing(io.BytesIO(json.dumps({"meta": {"code": 403}}).encode()))

        with self.assertRaisesRegex(RuntimeError, "код 403") as error:
            add_catalog_dates([{"source": "2gis", "source_id": "42"}], "secret-key", opener)
        self.assertNotIn("secret-key", str(error.exception))

    def test_validation_rejects_wrong_host_and_invalid_limits(self):
        for change in ({"url": "https://example.org/"}, {"limit": 0}, {"delay": 0}):
            with self.assertRaises(ValueError):
                validate_job({"source": "yandex", "city": "Москва", "query": "кафе", **change})


class FakeEspo(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.headers.get("X-Api-Key") != "test-key":
            return self.respond(401, {})
        if self.server.unavailable:
            return self.respond(503, {})
        parts = urlsplit(self.path)
        if parts.path.endswith("/Lead"):
            where = json.loads(parse_qs(parts.query).get("searchParams", ["{}"])[0]).get("where", [])
            items = [r for r in self.server.records.values() if not where or r["cLeadgenId"] == where[0]["value"]]
            return self.respond(200, {"list": items, "total": len(items)})
        self.respond(200, self.server.records[parts.path.rsplit("/", 1)[1]])

    def do_POST(self):
        self.server.posts += 1
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        item_id = str(len(self.server.records) + 1)
        data["id"] = item_id
        self.server.records[item_id] = data
        if self.server.lose_ack:
            self.server.lose_ack = False
            self.close_connection = True
            return
        self.respond(200, data)

    def do_PUT(self):
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        item = self.server.records[self.path.rsplit("/", 1)[1]]
        item.update(data)
        self.respond(200, item)


class ApiIntegrationTest(unittest.TestCase):
    def setUp(self):
        StoreTest.setUp(self)
        # An in-memory HTTP transport works even in sandboxes that disallow sockets.
        from types import SimpleNamespace
        self.server = SimpleNamespace(records={}, posts=0, unavailable=False, lose_ack=False)
        self.addCleanup(patch.stopall)
        patch("leadgen.crm.urlopen", self.transport).start()
        self.client = EspoClient("http://espocrm.test", "test-key", sleep=lambda _: None)

    def transport(self, request, **kwargs):
        self.assertEqual(request.get_header("X-api-key"), "test-key")
        if self.server.unavailable:
            raise HTTPError(request.full_url, 503, "Unavailable", {}, None)
        parts = urlsplit(request.full_url)
        method = request.get_method()
        if method == "GET" and parts.path.endswith("/Lead"):
            # EspoCRM ignores a string-valued `where`; JSON belongs in `searchParams`.
            where = json.loads(parse_qs(parts.query).get("searchParams", ["{}"])[0]).get("where", [])
            items = [r for r in self.server.records.values() if not where or r["cLeadgenId"] == where[0]["value"]]
            data = {"list": items, "total": len(items)}
        elif method == "GET":
            data = self.server.records[parts.path.rsplit("/", 1)[1]]
        elif method == "POST":
            self.server.posts += 1
            data = json.loads(request.data)
            item_id = str(len(self.server.records) + 1)
            data["id"] = item_id
            self.server.records[item_id] = data
            if self.server.lose_ack:
                self.server.lose_ack = False
                raise URLError("Connection lost after commit")
        else:
            data = self.server.records[parts.path.rsplit("/", 1)[1]]
            data.update(json.loads(request.data))
        return io.BytesIO(json.dumps(data).encode())

    def test_real_http_transport(self):
        # Use the same contract over a real local socket where permitted.
        try:
            server = ThreadingHTTPServer(("127.0.0.1", 0), FakeEspo)
        except PermissionError:
            self.skipTest("Среда запрещает создание локальных TCP-сокетов")
        server.records, server.posts, server.unavailable, server.lose_ack = {}, 0, False, False
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        from urllib.request import urlopen
        with patch("leadgen.crm.urlopen", urlopen):
            self.store.ingest(company())
            client = EspoClient(f"http://127.0.0.1:{server.server_port}", "test-key")
            self.assertEqual(sync(self.store, client)["pending"], 0)

    def test_full_import_then_enrichment_preserves_workflow_and_optout(self):
        self.store.ingest(company())
        self.assertEqual(sync(self.store, self.client)["synced"], 1)
        remote = self.server.records["1"]
        remote.update({"status": "In Process", "description": "Перезвонить завтра", "assignedUserId": "manager-1"})
        remote["phoneNumberData"][0]["optOut"] = True
        self.store.ingest(company(source="2gis", source_id="22", email="hello@clinic.ru"))
        result = sync(self.store, self.client)
        self.assertEqual(result["pending"], 0)
        self.assertEqual(len(self.server.records), 1)
        self.assertEqual(remote["status"], "In Process")
        self.assertEqual(remote["description"], "Перезвонить завтра")
        self.assertEqual(remote["assignedUserId"], "manager-1")
        self.assertTrue(remote["phoneNumberData"][0]["optOut"])
        self.assertEqual(remote["emailAddressData"][0]["emailAddress"], "hello@clinic.ru")

    def test_server_commits_but_loses_ack_next_sync_does_not_create_duplicate(self):
        self.store.ingest(company())
        self.server.lose_ack = True
        self.assertEqual(sync(self.store, self.client)["pending"], 1)
        self.assertEqual(self.server.posts, 1)
        self.assertEqual(sync(self.store, self.client)["pending"], 0)
        self.assertEqual(self.server.posts, 1)

    def test_outage_retains_queue_and_restart_replays_it(self):
        self.store.ingest(company())
        self.server.unavailable = True
        self.assertEqual(sync(self.store, self.client)["pending"], 1)
        self.server.unavailable = False
        reopened = Store(self.store.path)
        self.assertEqual(sync(reopened, self.client)["pending"], 0)

    def test_separate_branches_create_separate_crm_records(self):
        first = self.store.ingest(company())
        second = self.store.ingest(company(source_id="102", address="Ленина, 2"))
        self.assertEqual(sync(self.store, self.client)["synced"], 2)
        self.assertEqual(len(self.server.records), 2)
        self.assertEqual({r["cLeadgenId"] for r in self.server.records.values()}, {first, second})

    def test_2gis_catalog_date_is_sent_to_crm(self):
        self.store.ingest(normalize({"source": "2gis", "source_id": "303", "name": "Новая точка",
                                     "gis_created_at": "2025-03-04T10:11:12+03:00"}))
        self.assertEqual(sync(self.store, self.client)["pending"], 0)
        self.assertEqual(self.server.records["1"]["cGisCreatedAt"], "2025-03-04T10:11:12+03:00")

    def test_source_specific_ratings_are_sent_to_crm(self):
        self.store.ingest(company(rating=4.7, reviews=81))
        self.store.ingest(company(source="2gis", source_id="404", rating=4.2, reviews=19))
        self.assertEqual(sync(self.store, self.client)["pending"], 0)
        remote = self.server.records["1"]
        self.assertEqual((remote["cYandexRating"], remote["cYandexReviews"]), (4.7, 81))
        self.assertEqual((remote["cGisRating"], remote["cGisReviews"]), (4.2, 19))

    def test_ignored_search_filter_cannot_overwrite_an_unrelated_lead(self):
        self.store.ingest(company())
        self.assertEqual(sync(self.store, self.client)["synced"], 1)
        snapshot = json.dumps(self.server.records, sort_keys=True)
        self.store.ingest(company(source_id="102", address="Ленина, 2"))
        transport = self.transport

        def ignored_filter(request, **kwargs):
            if request.get_method() == "GET" and urlsplit(request.full_url).path.endswith("/Lead"):
                return io.BytesIO(json.dumps({"list": list(self.server.records.values())}).encode())
            return transport(request, **kwargs)

        with patch("leadgen.crm.urlopen", ignored_filter):
            result = sync(self.store, self.client)
        self.assertEqual(result["synced"], 0)
        self.assertEqual(result["pending"], 1)
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(json.dumps(self.server.records, sort_keys=True), snapshot)

    def test_invalid_company_does_not_block_other_pending_companies(self):
        invalid_id = self.store.ingest(company(name="Invalid company"))
        self.store.ingest(company(source_id="102", address="Ленина, 2"))
        transport = self.transport

        def reject_invalid(request, **kwargs):
            if request.get_method() == "POST" and json.loads(request.data)["accountName"] == "Invalid company":
                raise HTTPError(request.full_url, 400, "Validation failed", {}, None)
            return transport(request, **kwargs)

        with patch("leadgen.crm.urlopen", reject_invalid):
            result = sync(self.store, self.client)
        self.assertEqual(result["synced"], 1)
        self.assertEqual(result["pending"], 1)
        self.assertEqual(result["errors"][0]["id"], invalid_id)
        self.assertIsNotNone(self.store.companies(True)[0]["error"])

    def test_outage_or_authentication_failure_stops_batch(self):
        self.store.ingest(company())
        self.store.ingest(company(source_id="102", address="Ленина, 2"))
        for code, attempts in ((503, 3), (401, 1), (403, 1), (400, 1)):
            with self.subTest(code=code):
                with patch("leadgen.crm.urlopen", side_effect=HTTPError(
                        "http://espocrm.test", code, "Unavailable", {}, None)) as transport:
                    result = sync(self.store, self.client)
                self.assertEqual(result["pending"], 2)
                self.assertEqual(len(result["errors"]), 1)
                self.assertEqual(transport.call_count, attempts)


if __name__ == "__main__":
    unittest.main()
