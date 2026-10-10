"""V0.1: contratos da vida (spec §1), leitor do ``[vida]`` e esqueleto dos módulos."""

import inspect
from pathlib import Path

import pytest
from wired import reactions
from wired.reacoes import diretor, episodio, estado, momento, repouso, vida
from wired.reacoes.contratos import Passo
from wired.reacoes.vida import VIDA_PADRAO, Causa, Cena, Evento, Faixa, Filtro, Fone, Momento, Repouso


def test_enums_do_acordo():
    assert [f.name for f in Faixa] == ["RADIANTE", "CONTENTE", "NEUTRA", "EMBURRADA"]
    assert len(Momento) == 13 and Momento.A_TOA == "a_toa"
    assert set(Filtro) == {Filtro.MADRUGADA, Filtro.PEDRO_MAL}
    assert set(Fone) == {Fone.CABECA, Fone.PESCOCO}
    # todo momento menos conversa/alerta tem média de passiva
    assert set(VIDA_PADRAO["passiva_media_min"]) == {m.value for m in Momento} - {"conversa", "alerta"}


def test_dataclasses():
    ev = Evento("ado", "musica", 1.0)
    with pytest.raises(AttributeError):
        ev.tipo = "x"  # type: ignore[misc]
    assert Causa("Ado tocou", 0.4, 2.0).delta == 0.4
    r = Repouso("B1", "C1", Fone.CABECA, "calm")
    assert r.sway is False and r.efeitos == ()
    c = Cena("musica_comecou", None, "musica", (Passo(200, eyes="B1"),), nivel=2)
    assert c.passos[0].ms == 200 and c.nivel == 2


def test_mesclar_profunda_nao_muda_base():
    out = vida.mesclar(VIDA_PADRAO, {"humor": {"limiar": {"radiante": 0.6}}}, {"cenas_hora": 5})
    assert out["humor"]["limiar"] == {"radiante": 0.6, "contente": 0.05, "emburrada": -0.35}
    assert out["humor"]["base_animo"] == 0.15 and out["cenas_hora"] == 5
    assert VIDA_PADRAO["humor"]["limiar"]["radiante"] == 0.5


def test_padrao_bate_com_o_gosto_do_conselho():
    """VIDA_PADRAO é a transcrição do [vida] do persona/condessa-gosto.toml."""
    t = reactions.Taste(council_file=reactions.COUNCIL_FILE)
    assert reactions._load_toml(reactions.COUNCIL_FILE)["vida"] == VIDA_PADRAO
    assert t.vida() == VIDA_PADRAO


def test_vida_pedro_por_cima(tmp_path: Path):
    conselho = tmp_path / "conselho.toml"
    conselho.write_text("[vida]\ncenas_hora = 8\n[vida.humor]\nhisterese = 0.05\n", encoding="utf-8")
    mine = tmp_path / "gosto.toml"
    mine.write_text("[vida]\ncenas_hora = 4\n[vida.humor.limiar]\nradiante = 0.7\n", encoding="utf-8")
    t = reactions.Taste(council_file=conselho, taste_file=mine)
    v = t.vida()
    assert v["cenas_hora"] == 4
    assert v["humor"]["limiar"] == {"radiante": 0.7, "contente": 0.05, "emburrada": -0.35}
    assert v["humor"]["histerese"] == 0.05 and v["jogo"]["cobrancas_partida"] == 2
    assert t.vida() is v  # cache enquanto os arquivos não mudam


def test_vida_sem_arquivos_usa_padrao(tmp_path: Path):
    t = reactions.Taste(council_file=tmp_path / "nada.toml", taste_file=tmp_path / "nada2.toml")
    assert t.vida() == VIDA_PADRAO


def test_estado_isolado(tmp_path: Path):
    assert Path(estado.ESTADO_FILE).is_relative_to(tmp_path)


def test_esqueleto_assinaturas():
    assert list(inspect.signature(momento.decidir).parameters) == ["ctx", "anterior", "agora"]
    assert list(inspect.signature(momento.filtros).parameters) == ["ctx"]
    params = ["momento", "faixa", "filtros", "postura", "ctx"]
    assert list(inspect.signature(repouso.rosto).parameters) == params
    for nome in ("aplicar", "tick", "faixa", "medidor"):
        assert callable(getattr(estado.Humor, nome))
    assert callable(estado.Estado.salvar) and callable(estado.Estado.carregar)
    d = diretor.Diretor(estado.Estado())
    assert d.cfg == {}
    with pytest.raises(NotImplementedError):
        d.proxima(0.0)
    with pytest.raises(NotImplementedError):
        episodio.Episodio().game_on(0.0)
