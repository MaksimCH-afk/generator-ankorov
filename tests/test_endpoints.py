"""End-to-end endpoint tests via FastAPI TestClient (isolated temp DB)."""
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import Project, Strategy


def _project_id(url: str) -> int:
    db = SessionLocal()
    try:
        return db.query(Project).filter(Project.url == url).first().id
    finally:
        db.close()


def test_health_and_pages():
    with TestClient(app) as c:
        assert c.get("/health").json()["status"] == "ok"
        for p in ["/", "/generate", "/schedule", "/anchor-types", "/strategies", "/profiles",
                  "/suffixes", "/history", "/logs", "/anchors"]:
            assert c.get(p).status_code == 200


def test_create_dedup_and_normalize():
    with TestClient(app) as c:
        c.post("/projects/create", data={"url": "http://www.dedup-test.com", "language": "English"},
               follow_redirects=False)
        # www stripped + https forced + trailing slash
        pid = _project_id("https://dedup-test.com/")
        assert pid
        # duplicate (different form, same canonical) is rejected
        r = c.post("/projects/create", data={"url": "https://www.dedup-test.com/"}, follow_redirects=False)
        assert "error=" in r.headers["location"]


def test_full_generation_flow_and_download():
    with TestClient(app) as c:
        c.post("/projects/create", data={"url": "https://flow.com/", "language": "German"},
               follow_redirects=False)
        pid = _project_id("https://flow.com/")
        # upload keywords
        csv = b"keyword,frequency\nflow,1000\nflow casino,500\nflow login,100\n"
        c.post(f"/projects/{pid}/keywords", files={"file": ("f.csv", csv, "text/csv")},
               follow_redirects=False)
        sid = SessionLocal().query(Strategy).first().id  # "Обычная"
        c.post(f"/projects/{pid}/strategy", data={"strategy_id": sid, "next": f"/projects/{pid}"},
               follow_redirects=False)
        c.post(f"/projects/{pid}/volume", data={"volume": 50}, follow_redirects=False)
        # generate -> JSON token
        r = c.post("/generate", data={"project_ids": [pid], "sprint": "122",
                                      "export_format": "separate", "group_mode": "expand"})
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 50 and body["count"] == 1
        token = body["token"]
        # download once -> xlsx; twice -> gone
        d = c.get(f"/generate/download/{token}")
        assert d.status_code == 200 and "spreadsheet" in d.headers["content-type"]
        d2 = c.get(f"/generate/download/{token}", follow_redirects=False)
        assert d2.status_code == 303


def test_export_and_breakdown():
    with TestClient(app) as c:
        c.post("/projects/create", data={"url": "https://exp.com/", "language": ""}, follow_redirects=False)
        pid = _project_id("https://exp.com/")
        c.post(f"/projects/{pid}/keywords",
               files={"file": ("f.csv", b"keyword,frequency\nexp,100\n", "text/csv")}, follow_redirects=False)
        sid = SessionLocal().query(Strategy).first().id
        c.post(f"/projects/{pid}/strategy", data={"strategy_id": sid}, follow_redirects=False)
        c.post(f"/projects/{pid}/volume", data={"volume": 20}, follow_redirects=False)
        # breakdown JSON
        rows = c.get(f"/projects/{pid}/breakdown").json()["rows"]
        assert rows and sum(r["count"] for r in rows) == 20
        # one-click export
        e = c.get(f"/projects/{pid}/export")
        assert e.status_code == 200 and "spreadsheet" in e.headers["content-type"]


def test_duplicate_project_reuses_keywords():
    with TestClient(app) as c:
        c.post("/projects/create", data={"url": "https://dup-src.com/", "language": "German",
                                         "brand": "DupBrand"}, follow_redirects=False)
        pid = _project_id("https://dup-src.com/")
        c.post(f"/projects/{pid}/keywords",
               files={"file": ("f.csv", b"keyword,frequency\na,100\nb,50\nc,10\n", "text/csv")},
               follow_redirects=False)
        sid = SessionLocal().query(Strategy).first().id
        c.post(f"/projects/{pid}/strategy", data={"strategy_id": sid}, follow_redirects=False)
        c.post(f"/projects/{pid}/volume", data={"volume": 250}, follow_redirects=False)
        # duplicate to two mirror domains, keep the source strategy
        r = c.post(f"/projects/{pid}/duplicate",
                   data={"domains": "https://dup-m1.com/\ndup-m2.at", "strategy": "keep"},
                   follow_redirects=False)
        assert r.status_code == 303
        db = SessionLocal()
        for url in ("https://dup-m1.com/", "https://dup-m2.at/"):
            clone = db.query(Project).filter(Project.url == url).first()
            assert clone is not None
            assert len(clone.keywords) == 3          # keywords copied
            assert clone.language == "German" and clone.brand == "DupBrand"
            assert clone.volume == 250 and clone.strategy_id == sid
        db.close()
        # duplicating onto an existing domain is skipped
        r2 = c.post(f"/projects/{pid}/duplicate",
                    data={"domains": "https://dup-m1.com/", "strategy": "keep"}, follow_redirects=False)
        assert "location" in r2.headers


def test_bulk_and_anchors():
    with TestClient(app) as c:
        c.post("/projects/create", data={"url": "https://b1.com/"}, follow_redirects=False)
        c.post("/projects/create", data={"url": "https://b2.com/"}, follow_redirects=False)
        id1, id2 = _project_id("https://b1.com/"), _project_id("https://b2.com/")
        r = c.post("/projects/bulk-delete", data={"project_ids": [id1, id2]}, follow_redirects=False)
        assert r.status_code == 303
        db = SessionLocal()
        assert db.get(Project, id1) is None and db.get(Project, id2) is None
        db.close()
        # anchors add + delete
        c.post("/anchors/add", data={"phrases": "casino spam\nwelcome bonus"}, follow_redirects=False)
        assert c.get("/anchors").status_code == 200
