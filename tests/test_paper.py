import pytest

from tradingbot.costs import CostModel
from tradingbot.demo import synthetic_candles
from tradingbot.models import Candle
from tradingbot.paper import PaperEngine, run_id_for
from tradingbot.risk import RiskManager
from tradingbot.storage import Store
from tradingbot.strategy.sma_cross import SmaCross

TF = 3600
FREE = CostModel(taker_fee_bps=0, maker_fee_bps=0, half_spread_bps=0, slippage_bps=0)


def engine(store, strategy=None, costs=None, cash=100.0, risk=None):
    return PaperEngine(
        store=store,
        book="usd_ars",
        tf=TF,
        strategy=strategy or SmaCross(3, 8),
        starting_cash=cash,
        costs=costs or FREE,
        risk=risk or RiskManager(max_daily_loss_pct=10.0, min_order_notional=1.0),
    )


@pytest.fixture
def store(tmp_path):
    with Store(tmp_path / "paper.db") as s:
        yield s


def seed(store, n=60, **kwargs):
    candles = synthetic_candles(n=n, tf=TF, seed=7, **kwargs)
    store.upsert_candles("usd_ars", TF, candles)
    return candles


def test_run_id_is_stable_across_instances():
    """Si el run_id cambiara en cada arranque, cada deploy partiria la
    evidencia en pedazos y el criterio de fase nunca se alcanzaria."""
    assert run_id_for("usd_ars", TF, SmaCross(3, 8)) == run_id_for(
        "usd_ars", TF, SmaCross(3, 8)
    )


def test_forming_candle_is_not_traded(store):
    """La ultima vela sigue recibiendo trades: operarla es decidir con datos
    incompletos, y la senal cambiaria a medida que llegan operaciones."""
    candles = seed(store, n=10)
    eng = engine(store)
    last = candles[-1]

    mid = eng.closed_candles(now=last.ts + TF // 2)
    closed = eng.closed_candles(now=last.ts + TF)

    assert len(mid) == 9
    assert mid[-1].ts == candles[-2].ts
    assert len(closed) == 10


def test_candles_are_processed_once(store):
    candles = seed(store, n=40)
    now = candles[-1].ts + TF

    first = engine(store).step(now=now)
    assert first.processed == 40

    second = engine(store).step(now=now)
    assert second.processed == 0


def test_state_survives_restart(store):
    candles = seed(store, n=60)
    before = engine(store)
    before.step(now=candles[-1].ts + TF)

    after = engine(store)
    assert after.broker.cash == pytest.approx(before.broker.cash)
    assert after.broker.position == pytest.approx(before.broker.position)
    assert after.last_candle_ts == before.last_candle_ts


def test_new_candles_continue_the_same_run(store):
    candles = synthetic_candles(n=60, tf=TF, seed=7)
    store.upsert_candles("usd_ars", TF, candles[:30])
    first = engine(store).step(now=candles[29].ts + TF)

    store.upsert_candles("usd_ars", TF, candles)
    second = engine(store).step(now=candles[-1].ts + TF)

    assert first.processed == 30
    assert second.processed == 30
    assert second.last_candle_ts == candles[-1].ts


def test_no_trades_before_warmup(store):
    candles = synthetic_candles(n=5, tf=TF, seed=7)
    store.upsert_candles("usd_ars", TF, candles)
    result = engine(store, strategy=SmaCross(10, 30)).step(now=candles[-1].ts + TF)
    assert result.processed == 5
    assert result.fills == 0


def test_kill_switch_persists_across_restart(store):
    """Un bot que se rearma solo reiniciando el contenedor no tiene kill switch."""
    seed(store, n=40)
    risk = RiskManager(max_daily_loss_pct=0.001, min_order_notional=1.0)
    eng = engine(store, risk=risk, costs=CostModel())
    eng.risk.halted = True
    eng.risk.halt_reason = "prueba"
    eng._persist(0, 0.0)

    revived = engine(store)
    assert revived.risk.halted
    assert revived.risk.halt_reason == "prueba"


def test_costs_reduce_equity_versus_free(store):
    seed(store, n=80)
    now = 80 * TF
    free = engine(store).step(now=now)

    with Store(store.path.parent / "b.db") as other:
        other.upsert_candles("usd_ars", TF, synthetic_candles(n=80, tf=TF, seed=7))
        real = engine(other, costs=CostModel()).step(now=now)

    assert real.equity < free.equity


def test_fills_and_rejections_are_journaled(store):
    candles = seed(store, n=60)
    eng = engine(store)
    result = eng.step(now=candles[-1].ts + TF)

    logged = len(store.run_entries(eng.run_id, kind="fill"))
    assert logged == result.fills
    assert result.fills > 0


def test_flat_market_produces_no_trades(store):
    flat = [Candle(i * TF, 100.0, 100.0, 100.0, 100.0, 1.0) for i in range(40)]
    store.upsert_candles("usd_ars", TF, flat)
    result = engine(store).step(now=40 * TF)
    assert result.fills == 0


# --- verificacion del libro ------------------------------------------------

class FakeClient:
    def __init__(self, books=None, error=None):
        self._books = books or []
        self._error = error

    def available_books(self):
        if self._error:
            raise self._error
        return [{"book": b} for b in self._books]


def test_known_book_passes_verification():
    from tradingbot.daemon import verify_book

    verify_book(FakeClient(["usdc_ars", "btc_ars"]), "usdc_ars")


def test_unknown_book_aborts_with_suggestions():
    """Un libro mal escrito debe fallar como error de configuracion, no
    convertirse en un proceso que parece vivo y nunca junta un dato."""
    from tradingbot.daemon import verify_book

    with pytest.raises(SystemExit) as exc:
        verify_book(FakeClient(["usdc_ars", "btc_mxn"]), "usdc_arss")
    message = str(exc.value)
    assert "no existe" in message
    assert "usdc_ars" in message


def test_network_failure_does_not_abort():
    """Un fallo de red es transitorio: lo maneja el backoff del ciclo."""
    from tradingbot.daemon import verify_book
    from tradingbot.exchange.bitso import BitsoError

    verify_book(FakeClient(error=BitsoError("sin red")), "usdc_ars")
