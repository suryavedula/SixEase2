"""Live provider smoke test (real API calls) — run manually, never in CI.

Validates that the hackathon credentials in the root `.env` actually reach
SIX (MCP), Event Registry (news), and the LLM backend. Unlike tests/test_*.py
(which mock the network), this hits the real endpoints.

    docker exec -e SIX_MCP_TOKEN=... -e NEWSAPI_KEY=... \
        -e PHOENIQS_API_KEY=... -e LLM_PROVIDER=phoeniqs \
        wealth-backend-1 python tests/live_smoke.py
"""
import asyncio

from app.config import get_settings
from app import six, news, llm


async def check_six() -> tuple[bool, str]:
    try:
        ok = await six.ping_six()
        if not ok:
            return False, "ping_six() returned False"
        hits = await six.find_instrument("Amazon", size=3)
        if not hits:
            return False, "ping ok but find_instrument('Amazon') returned 0 rows"
        top = hits[0]
        # Auth + connectivity proven by ping+find. EOD/intraday is best-effort:
        # on weekends/holidays a venue may have no close, which is data, not a fault.
        listing = f"{top.valor}_{top.mic}"
        try:
            snap = await six.get_eod_snapshot(listing)
            quote = f"EOD close={snap.close} {snap.currency} @ {snap.timestamp}"
        except Exception as exc:  # noqa: BLE001
            quote = f"no EOD ({exc}); retrying intraday…"
            try:
                intra = await six.get_intraday_snapshot(listing)
                quote += f" intraday last={intra.last} @ {intra.timestamp}"
            except Exception as exc2:  # noqa: BLE001
                quote += f" no intraday either ({exc2}) — likely non-trading day"
        return True, f"find→{top.name} valor={top.valor} mic={top.mic}; {quote}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        await six.close_six()


async def check_news() -> tuple[bool, str]:
    try:
        ok = await news.ping_news()
        if not ok:
            return False, "ping_news() returned False"
        arts = await news.search_articles(keywords=["Novartis"])
        if not arts:
            return True, "ping ok; search('Novartis') returned 0 articles (key valid, empty result)"
        a = arts[0]
        return True, (
            f"{len(arts)} articles; top='{a.title[:60]}' "
            f"source={a.source} sentiment={a.sentiment}"
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        await news.close_news()


async def check_llm() -> tuple[bool, str]:
    cfg = get_settings().llm
    try:
        ok = await llm.ping_llm()
        if not ok:
            return False, f"ping_llm() returned False (provider={cfg.provider}, base={cfg.base_url})"
        reply = await llm.chat(
            [{"role": "user", "content": "Reply with exactly the word: PONG"}],
            max_tokens=512,  # gpt-oss-120b is a reasoning model; small budgets yield empty content
        )
        return True, f"provider={cfg.provider} model={cfg.model} reply={reply.strip()!r}"
    except Exception as exc:  # noqa: BLE001
        return False, f"provider={cfg.provider}: {type(exc).__name__}: {exc}"
    finally:
        await llm.close_llm()


async def main() -> int:
    print("=== Live provider smoke test ===\n")
    results = {
        "SIX (MCP)": await check_six(),
        "News (Event Registry)": await check_news(),
        "LLM": await check_llm(),
    }
    failures = 0
    for name, (ok, detail) in results.items():
        mark = "PASS" if ok else "FAIL"
        if not ok:
            failures += 1
        print(f"[{mark}] {name}: {detail}\n")
    print(f"=== {len(results) - failures}/{len(results)} providers reachable ===")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
