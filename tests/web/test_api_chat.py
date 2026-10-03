from uuid import UUID

from chat_api_fixtures import BASE_URL, CHATS_URL, ChatApp, chat_app

from sbobina.web.chat_store import chat_path

__all__ = ["chat_app"]


def test_create_chat_returns_uuid_and_lists_it(chat_app: ChatApp) -> None:
    response = chat_app.client.post(CHATS_URL)

    assert response.status_code == 201
    chat_id = response.json()["data"]["id"]
    assert str(UUID(chat_id)) == chat_id
    listed = chat_app.client.get(CHATS_URL).json()
    assert [chat["id"] for chat in listed["data"]] == [chat_id]
    assert listed["meta"]["total"] == 1


def test_create_chat_unknown_course_is_not_found(chat_app: ChatApp) -> None:
    response = chat_app.client.post("/api/v1/courses/sconosciuto/chats")

    assert response.status_code == 404


def test_message_answers_with_resolved_lecture_citation(chat_app: ChatApp) -> None:
    chat_id = chat_app.new_chat()

    response = chat_app.ask(chat_id=chat_id)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["outcome"] == "DONE"
    citation = data["sentences"][0]["citations"][0]
    assert citation["href"].startswith("/lettore/")
    detail = chat_app.client.get(f"{CHATS_URL}/{chat_id}").json()["data"]
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]


def test_message_without_material_is_not_found_without_calling_the_model(
    chat_app: ChatApp,
) -> None:
    chat_id = chat_app.new_chat()

    response = chat_app.ask(chat_id=chat_id, question="chi ha vinto i mondiali?")

    assert response.json()["data"]["outcome"] == "NOT_FOUND"
    assert chat_app.model.requests == []


def test_message_validation_errors_name_the_field(chat_app: ChatApp) -> None:
    chat_id = chat_app.new_chat()

    for question in ("", "x" * 1001):
        response = chat_app.ask(chat_id=chat_id, question=question)
        assert response.status_code == 422
        fields = [d["field"] for d in response.json()["error"]["details"]]
        assert any("question" in name for name in fields)


def test_unknown_or_malformed_chat_id_is_not_found(chat_app: ChatApp) -> None:
    for chat_id in ("00000000-0000-4000-8000-000000000000", "non-un-uuid", "..."):
        assert chat_app.client.get(f"{CHATS_URL}/{chat_id}").status_code == 404
        assert chat_app.ask(chat_id=chat_id).status_code == 404


def test_delete_chat_then_it_is_gone(chat_app: ChatApp) -> None:
    chat_id = chat_app.new_chat()

    assert chat_app.client.delete(f"{CHATS_URL}/{chat_id}").status_code == 204
    assert chat_app.client.get(f"{CHATS_URL}/{chat_id}").status_code == 404
    assert chat_app.client.delete(f"{CHATS_URL}/{chat_id}").status_code == 404


def test_foreign_origin_rejected_on_post_and_delete(chat_app: ChatApp) -> None:
    chat_id = chat_app.new_chat()
    foreign = {"Origin": "http://evil.example"}

    assert chat_app.client.post(CHATS_URL, headers=foreign).status_code == 403
    assert (
        chat_app.client.delete(f"{CHATS_URL}/{chat_id}", headers=foreign).status_code
        == 403
    )
    assert chat_app.client.get(f"{CHATS_URL}/{chat_id}").status_code == 200
    assert BASE_URL.startswith("http://127.0.0.1")


def test_corrupt_line_is_skipped_not_a_server_error(chat_app: ChatApp) -> None:
    chat_id = chat_app.new_chat()
    chat_app.ask(chat_id=chat_id)
    path = (
        chat_app.store.courses_dir / chat_app.course_id / "chats" / f"{chat_id}.jsonl"
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{rotta\n")

    response = chat_app.client.get(f"{CHATS_URL}/{chat_id}")

    assert response.status_code == 200
    assert len(response.json()["data"]["messages"]) == 2


def test_get_chat_whose_file_lost_its_meta_line_is_not_found(
    chat_app: ChatApp,
) -> None:
    chat_id = chat_app.new_chat()
    chat_app.ask(chat_id=chat_id)
    path = chat_path(
        courses_dir=chat_app.store.courses_dir,
        course_id=chat_app.course_id,
        chat_id=chat_id,
    )
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(lines[1:]) + "\n", encoding="utf-8")

    response = chat_app.client.get(f"{CHATS_URL}/{chat_id}")

    assert chat_app.lines(chat_id)[0]["kind"] == "question"
    assert response.status_code == 404
