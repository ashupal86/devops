import pytest

from app.schemas import MAX_LINKS


# ---------- create ----------


def test_create_returns_profile_and_token(client, profile_payload):
    res = client.post("/api/profiles", json=profile_payload)
    assert res.status_code == 201
    body = res.json()
    assert body["edit_token"] and len(body["edit_token"]) >= 32
    profile = body["profile"]
    assert profile["tag"] == "ada"
    assert profile["display_name"] == "Ada Lovelace"
    assert profile["links"] == profile_payload["links"]
    assert "edit_token_hash" not in profile
    assert "id" not in profile


def test_create_normalizes_tag_and_strips_whitespace(client, profile_payload):
    profile_payload.update(tag="  Ada_Dev ", display_name="  Ada  ")
    res = client.post("/api/profiles", json=profile_payload)
    assert res.status_code == 201
    assert res.json()["profile"]["tag"] == "ada_dev"
    assert res.json()["profile"]["display_name"] == "Ada"


def test_create_minimal_profile(client):
    res = client.post("/api/profiles", json={"tag": "min", "display_name": "Min"})
    assert res.status_code == 201
    assert res.json()["profile"]["message"] == ""
    assert res.json()["profile"]["links"] == []


def test_create_duplicate_tag_conflicts(client, created, profile_payload):
    profile_payload["tag"] = "ADA"  # case-insensitive clash
    res = client.post("/api/profiles", json=profile_payload)
    assert res.status_code == 409


@pytest.mark.parametrize(
    "tag",
    ["ab", "a" * 31, "has space", "-lead", "trail-", "bad!", "emoji😀", "api", "edit", ""],
)
def test_create_rejects_invalid_tags(client, profile_payload, tag):
    profile_payload["tag"] = tag
    assert client.post("/api/profiles", json=profile_payload).status_code == 422


@pytest.mark.parametrize(
    "field,value",
    [
        ("display_name", ""),
        ("display_name", "   "),
        ("display_name", "x" * 81),
        ("message", "x" * 501),
    ],
)
def test_create_rejects_invalid_fields(client, profile_payload, field, value):
    profile_payload[field] = value
    assert client.post("/api/profiles", json=profile_payload).status_code == 422


@pytest.mark.parametrize(
    "url",
    ["javascript:alert(1)", "ftp://example.com", "example.com", "https://", "/relative"],
)
def test_create_rejects_unsafe_or_invalid_urls(client, profile_payload, url):
    profile_payload["links"] = [{"label": "Bad", "url": url}]
    assert client.post("/api/profiles", json=profile_payload).status_code == 422


def test_create_rejects_empty_link_label(client, profile_payload):
    profile_payload["links"] = [{"label": " ", "url": "https://ok.example"}]
    assert client.post("/api/profiles", json=profile_payload).status_code == 422


def test_create_rejects_too_many_links(client, profile_payload):
    profile_payload["links"] = [
        {"label": f"L{i}", "url": f"https://x.com/{i}"} for i in range(MAX_LINKS + 1)
    ]
    assert client.post("/api/profiles", json=profile_payload).status_code == 422


def test_create_accepts_max_links(client, profile_payload):
    profile_payload["links"] = [
        {"label": f"L{i}", "url": f"https://x.com/{i}"} for i in range(MAX_LINKS)
    ]
    assert client.post("/api/profiles", json=profile_payload).status_code == 201


def test_each_profile_gets_unique_token(client):
    t1 = client.post("/api/profiles", json={"tag": "one", "display_name": "1"}).json()
    t2 = client.post("/api/profiles", json={"tag": "two", "display_name": "2"}).json()
    assert t1["edit_token"] != t2["edit_token"]


# ---------- read ----------


def test_get_profile(client, created):
    profile, _ = created
    res = client.get("/api/profiles/ada")
    assert res.status_code == 200
    assert res.json() == profile


def test_get_profile_is_case_insensitive(client, created):
    assert client.get("/api/profiles/ADA").status_code == 200


def test_get_missing_profile_404(client):
    assert client.get("/api/profiles/nobody").status_code == 404


# ---------- availability ----------


def test_tag_available(client):
    res = client.get("/api/profiles/fresh/available")
    assert res.json() == {"tag": "fresh", "available": True, "reason": None}


def test_tag_taken(client, created):
    body = client.get("/api/profiles/Ada/available").json()
    assert body["available"] is False
    assert body["reason"] == "already taken"


@pytest.mark.parametrize("tag", ["ab", "api", "bad!"])
def test_tag_invalid_is_unavailable(client, tag):
    body = client.get(f"/api/profiles/{tag}/available").json()
    assert body["available"] is False
    assert body["reason"]


# ---------- update ----------


def test_update_with_valid_token(client, created):
    _, token = created
    new = {
        "display_name": "Ada L.",
        "message": "Updated",
        "links": [{"label": "Site", "url": "https://ada.dev"}],
    }
    res = client.put("/api/profiles/ada", json=new, headers={"X-Edit-Token": token})
    assert res.status_code == 200
    assert res.json()["display_name"] == "Ada L."
    assert res.json()["links"] == new["links"]
    assert client.get("/api/profiles/ada").json()["message"] == "Updated"


def test_update_cannot_change_tag(client, created):
    _, token = created
    res = client.put(
        "/api/profiles/ada",
        json={"tag": "hijack", "display_name": "Ada"},
        headers={"X-Edit-Token": token},
    )
    assert res.status_code == 200
    assert res.json()["tag"] == "ada"
    assert client.get("/api/profiles/hijack").status_code == 404


def test_update_without_token_401(client, created):
    res = client.put("/api/profiles/ada", json={"display_name": "x"})
    assert res.status_code == 401


def test_update_with_wrong_token_403(client, created):
    res = client.put(
        "/api/profiles/ada", json={"display_name": "x"}, headers={"X-Edit-Token": "nope"}
    )
    assert res.status_code == 403
    assert client.get("/api/profiles/ada").json()["display_name"] == "Ada Lovelace"


def test_token_of_one_profile_cannot_edit_another(client, created):
    _, ada_token = created
    client.post("/api/profiles", json={"tag": "bob", "display_name": "Bob"})
    res = client.put(
        "/api/profiles/bob", json={"display_name": "pwned"}, headers={"X-Edit-Token": ada_token}
    )
    assert res.status_code == 403


def test_update_missing_profile_404(client):
    res = client.put(
        "/api/profiles/ghost", json={"display_name": "x"}, headers={"X-Edit-Token": "t"}
    )
    assert res.status_code == 404


def test_update_validates_body(client, created):
    _, token = created
    res = client.put(
        "/api/profiles/ada",
        json={"display_name": "Ada", "links": [{"label": "x", "url": "javascript:1"}]},
        headers={"X-Edit-Token": token},
    )
    assert res.status_code == 422


# ---------- delete ----------


def test_delete_with_valid_token(client, created):
    _, token = created
    res = client.delete("/api/profiles/ada", headers={"X-Edit-Token": token})
    assert res.status_code == 204
    assert client.get("/api/profiles/ada").status_code == 404
    # Tag is free again.
    assert client.get("/api/profiles/ada/available").json()["available"] is True


def test_delete_with_wrong_token_403(client, created):
    res = client.delete("/api/profiles/ada", headers={"X-Edit-Token": "wrong"})
    assert res.status_code == 403
    assert client.get("/api/profiles/ada").status_code == 200


def test_delete_without_token_401(client, created):
    assert client.delete("/api/profiles/ada").status_code == 401
