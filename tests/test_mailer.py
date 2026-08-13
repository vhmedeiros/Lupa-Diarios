"""Testes de app/mailer.py: regra dos 15MB (R2) e montagem do e-mail.

Não chama SMTP real — `build_email` só monta (subject, html_body,
attachments); enviar de verdade é a Fase 13.
"""

import datetime as dt

from app.mailer import build_email
from app.models import Publication

MB = 1024 * 1024


def _file(url: str, path: str, size_bytes: int) -> dict:
    return {"url": url, "path": path, "size_bytes": size_bytes, "attached": False}


def _publication(
    portal_code: str = "TCU",
    portal_name: str = "Tribunal de Contas da União",
    title: str = "Publicação de teste",
    published_at: dt.date = dt.date(2026, 8, 13),
    page_url: str = "https://exemplo.gov.br/publicacao/1",
    summary: str | None = None,
    files: list[dict] | None = None,
) -> Publication:
    return Publication(
        portal_code=portal_code,
        portal_name=portal_name,
        title=title,
        published_at=published_at,
        page_url=page_url,
        summary=summary,
        files=files if files is not None else [],
        content_hash=f"hash-{portal_code}-{page_url}-{published_at.isoformat()}",
    )


def test_soma_dentro_do_limite_tudo_anexado() -> None:
    pub = _publication(
        files=[
            _file("https://exemplo.gov.br/a.pdf", "data/files/TCU/a.pdf", 5 * MB),
            _file("https://exemplo.gov.br/b.pdf", "data/files/TCU/b.pdf", 5 * MB),
        ]
    )

    subject, html_body, attachments = build_email([pub], max_attach_mb=15)

    assert all(f["attached"] for f in pub.files)
    assert [a["filename"] for a in attachments] == ["a.pdf", "b.pdf"]
    assert "acima do limite" not in html_body
    assert "a.pdf (anexado)" in html_body
    assert "b.pdf (anexado)" in html_body


def test_soma_estourando_no_meio_respeita_ordem_de_descoberta() -> None:
    pub = _publication(
        files=[
            _file("https://exemplo.gov.br/a.pdf", "data/files/TCU/a.pdf", 6 * MB),
            _file("https://exemplo.gov.br/b.pdf", "data/files/TCU/b.pdf", 6 * MB),
            # Essa soma (6+6+6=18MB) estoura o limite de 15MB neste terceiro arquivo.
            _file("https://exemplo.gov.br/c.pdf", "data/files/TCU/c.pdf", 6 * MB),
            # Mesmo pequeno, vem depois do estouro — também vira link.
            _file("https://exemplo.gov.br/d.pdf", "data/files/TCU/d.pdf", 1 * MB),
        ]
    )

    subject, html_body, attachments = build_email([pub], max_attach_mb=15)

    a, b, c, d = pub.files
    assert a["attached"] is True
    assert b["attached"] is True
    assert c["attached"] is False
    assert d["attached"] is False
    assert [att["filename"] for att in attachments] == ["a.pdf", "b.pdf"]
    assert "c.pdf (anexado)" not in html_body
    assert "d.pdf (anexado)" not in html_body
    assert "acima do limite de anexo de 15 MB" in html_body


def test_arquivo_individual_maior_que_o_limite_nunca_e_anexado() -> None:
    pub = _publication(
        files=[_file("https://exemplo.gov.br/enorme.pdf", "data/files/TCU/enorme.pdf", 42 * MB)]
    )

    subject, html_body, attachments = build_email([pub], max_attach_mb=15)

    assert pub.files[0]["attached"] is False
    assert attachments == []
    assert "42 MB" in html_body
    assert "acima do limite de anexo de 15 MB" in html_body
    assert "https://exemplo.gov.br/enorme.pdf" in html_body


def test_publicacao_sem_arquivos_ainda_aparece_no_corpo() -> None:
    pub = _publication(title="Só texto, sem anexos", summary="Resumo qualquer.")

    subject, html_body, attachments = build_email([pub], max_attach_mb=15)

    assert attachments == []
    assert "Só texto, sem anexos" in html_body
    assert "Resumo qualquer." in html_body


def test_multiplos_portais_mantem_ordem_de_descoberta_na_soma_global() -> None:
    pub_a = _publication(
        portal_code="TCU",
        portal_name="Tribunal de Contas da União",
        page_url="https://exemplo.gov.br/tcu/1",
        files=[_file("https://exemplo.gov.br/tcu1.pdf", "data/files/TCU/tcu1.pdf", 10 * MB)],
    )
    pub_b = _publication(
        portal_code="TST",
        portal_name="Tribunal Superior do Trabalho",
        page_url="https://exemplo.gov.br/tst/1",
        files=[_file("https://exemplo.gov.br/tst1.pdf", "data/files/TST/tst1.pdf", 10 * MB)],
    )

    # Ordem de descoberta: TCU primeiro, depois TST (ordem da lista de entrada).
    subject, html_body, attachments = build_email([pub_a, pub_b], max_attach_mb=15)

    assert pub_a.files[0]["attached"] is True
    assert pub_b.files[0]["attached"] is False
    assert [a["filename"] for a in attachments] == ["tcu1.pdf"]
    assert html_body.index("Tribunal de Contas da União") < html_body.index(
        "Tribunal Superior do Trabalho"
    )


def test_assunto_segue_formato_da_spec() -> None:
    pub_a = _publication(page_url="https://exemplo.gov.br/1")
    pub_b = _publication(page_url="https://exemplo.gov.br/2", published_at=dt.date(2026, 8, 14))
    moment = dt.datetime(2026, 8, 13, 9, 30)

    subject, _, _ = build_email([pub_a, pub_b], max_attach_mb=15, now=moment)

    assert subject == "Lupa Diários Oficiais — 2 novas publicações — 13/08/2026 09:30"


def test_build_email_nao_envia_nada_apenas_retorna_valores() -> None:
    pub = _publication()

    result = build_email([pub], max_attach_mb=15)

    assert isinstance(result, tuple)
    assert len(result) == 3
    subject, html_body, attachments = result
    assert isinstance(subject, str)
    assert isinstance(html_body, str)
    assert isinstance(attachments, list)
