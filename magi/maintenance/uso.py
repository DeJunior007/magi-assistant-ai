"""Relatório de uso real: as métricas de sucesso do PRD (tarefas 7.1/7.2) a partir do banco.

Uso: ``magi-uso [--dias 14] [--dsn ...]`` (de qualquer pasta; ou ``uv run magi-uso`` no repositório)

- **Uso:** interações por dia com uso (meta: ≥ 5 por dia de jogo depois de 2 semanas).
- **Entendimento:** correções a cada 20 interações (meta: < 1) e turnos sem texto/"não peguei".
- **Música:** pulos a cada 4 músicas escolhidas pelo "coloca uma boa" (meta: < 1).
- **Custo:** gasto do mês e projeção contra o teto (``[budget] monthly_usd``).

Rajadas de teste (o mesmo texto mais de ``BURST`` vezes na mesma hora, como baterias de
``tools.perf``) ficam fora da conta. FPS com o Magui dormindo não sai do banco: ver
``docs/perf/``.
"""

from __future__ import annotations

import argparse
import asyncio
import calendar
from datetime import UTC, datetime, timedelta

import psycopg

BURST = 20  # mesmo texto mais que isso numa hora = bateria de teste
GOALS = {"uso": 5.0, "correcoes_20": 1.0, "pulos_4": 1.0}
NOT_UNDERSTOOD = ("não peguei", "nao peguei", "não entendi", "nao entendi", "me enrolei")

REAL_TURNS = f"""
with t as (
  select *, count(*) over (partition by date_trunc('hour', at), text_final) as same
  from turns where at >= %(since)s
)
select at, text_heard, text_final, intent, routed_local, reply from t where same <= {BURST}
"""


def month_projection(spent: float, now: datetime) -> float:
    days = calendar.monthrange(now.year, now.month)[1]
    return spent / max(now.day - 1 + now.hour / 24, 0.5) * days


async def report(dsn: str, days: int, budget: float | None) -> str:
    now = datetime.now(UTC)
    since = now - timedelta(days=days)
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        rows = await (await conn.execute(REAL_TURNS, {"since": since})).fetchall()
        corrections = (
            (
                await (
                    await conn.execute("select count(*) from corrections where created_at >= %s", (since,))
                ).fetchone()
            )[0]
            if await _has_column(conn, "corrections", "created_at")
            else None
        )
        picked = await (
            await conn.execute(
                "select signal from music_signals where at >= %s and (context->>'picked')::bool", (since,)
            )
        ).fetchall()
        month0 = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        spent = float(
            (
                await (
                    await conn.execute("select coalesce(sum(usd), 0) from costs where at >= %s", (month0,))
                ).fetchone()
            )[0]
        )
    total = len(rows)
    by_day: dict[str, int] = {}
    for r in rows:
        day = r[0].astimezone().strftime("%Y-%m-%d")
        by_day[day] = by_day.get(day, 0) + 1
    local = sum(1 for r in rows if r[4])
    missed = sum(
        1 for r in rows if not (r[1] or "").strip() or any(w in (r[5] or "").lower() for w in NOT_UNDERSTOOD)
    )
    skips = sum(1 for (s,) in picked if s == -1)
    lines = [
        f"Uso real dos últimos {days} dias (rajadas de teste fora): {total} interações em {len(by_day)} dias"
    ]
    if by_day:
        avg = total / len(by_day)
        ok = "✔" if avg >= GOALS["uso"] else "✘"
        lines.append(
            f"  {ok} uso: {avg:.1f} por dia com uso (meta ≥ {GOALS['uso']:.0f})  ·  "
            + ", ".join(f"{d[5:]}: {n}" for d, n in sorted(by_day.items()))
        )
        lines.append(f"    locais {local} ({100 * local / total:.0f}%) · agente {total - local}")
    if total:
        per20 = (corrections or 0) / total * 20
        ok = "✔" if per20 < GOALS["correcoes_20"] else "✘"
        corr = "?" if corrections is None else str(corrections)
        lines.append(
            f"  {ok} correções: {corr} ({per20:.2f} a cada 20; meta < 1) · "
            f"não entendidos/vazios: {missed} ({100 * missed / total:.0f}%)"
        )
    if picked:
        per4 = skips / len(picked) * 4
        ok = "✔" if per4 < GOALS["pulos_4"] else "✘"
        lines.append(
            f'  {ok} "coloca uma boa": {skips} pulos em {len(picked)} escolhas '
            f'({per4:.2f} a cada 4; meta < 1)'
        )
    else:
        lines.append('  · "coloca uma boa": nenhuma escolha registrada no período')
    proj = month_projection(spent, now)
    if budget:
        ok = "✔" if proj <= budget else "✘"
        lines.append(f"  {ok} custo: US$ {spent:.2f} no mês, projeção US$ {proj:.2f} (teto US$ {budget:.2f})")
    else:
        lines.append(f"  · custo: US$ {spent:.2f} no mês, projeção US$ {proj:.2f}")
    if len(by_day) < 14:
        lines.append(f"  (ainda {14 - len(by_day)} dias com uso para fechar as 2 semanas do PRD)")
    return "\n".join(lines)


async def _has_column(conn, table: str, column: str) -> bool:
    row = await (
        await conn.execute(
            "select 1 from information_schema.columns where table_name = %s and column_name = %s",
            (table, column),
        )
    ).fetchone()
    return row is not None


def _budget() -> float | None:
    try:
        from magi.common.config import load_config

        raw = load_config().raw
        return float((raw.get("budget") or {}).get("monthly_usd"))
    except Exception:
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dias", type=int, default=14)
    ap.add_argument("--dsn", default=None, help="padrão: $MAGI_DB_DSN ou o Postgres local")
    args = ap.parse_args(argv)
    from magi.memory.migrate import dsn_from_env

    print(asyncio.run(report(args.dsn or dsn_from_env(), args.dias, _budget())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
