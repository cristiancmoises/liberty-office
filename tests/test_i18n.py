def test_errors_default_to_english_and_portuguese_is_explicit(env):
    _, client, _ = env
    assert client.get("/api/files").json()["detail"] == "Sign in to your account."
    assert (
        client.get("/api/files", headers={"Accept-Language": "pt-BR"}).json()["detail"]
        == "Entre na sua conta."
    )
    assert (
        client.post(
            "/api/files", content=b"no", headers={"Origin": "https://other.invalid"}
        ).json()["detail"]
        == "Origin not allowed."
    )
    assert (
        client.post(
            "/api/files",
            content=b"no",
            headers={"Origin": "https://other.invalid", "Accept-Language": "pt-BR"},
        ).json()["detail"]
        == "Origem não autorizada."
    )


def test_missing_source_offer_is_localized(tmp_path):
    from fastapi.testclient import TestClient

    from liberty.app import create_app
    from liberty.config import Settings

    settings = Settings(
        data_dir=tmp_path / "data", source_archive=tmp_path / "missing.zip"
    )
    with TestClient(create_app(settings), base_url=settings.origin) as client:
        assert client.get("/source.zip").json()["detail"] == (
            "The source offer is included in the Docker image and distribution package."
        )
        assert (
            client.get("/source.zip", headers={"Accept-Language": "pt-BR"})
            .json()["detail"]
            .startswith("A oferta de código fonte")
        )


def test_translation_never_changes_unknown_user_content():
    from types import SimpleNamespace

    from liberty.i18n import translate

    request = SimpleNamespace(headers={"accept-language": "en"})
    assert translate("Nome do meu arquivo", request) == "Nome do meu arquivo"
    assert translate({"name": "Arquivo não encontrado."}, request) == {
        "name": "Arquivo não encontrado."
    }
