def test_api_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    j = r.get_json()
    assert j.get("status") == "ok"


def test_api_health_with_cors_origin_header(client):
    r = client.get(
        "/api/health", headers={"Origin": "http://testclient.local"}
    )
    assert r.status_code == 200
    assert r.headers.get("Access-Control-Allow-Origin") == "http://testclient.local"
