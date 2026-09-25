"""Interfaz de linea de comandos.

    python -m tradingbot books
    python -m tradingbot spread --book usdc_ars
    python -m tradingbot collect --book usdc_ars
    python -m tradingbot backtest --book usdc_ars --tf 1h --fast 10 --slow 30
    python -m tradingbot balance
    python -m tradingbot costs
"""

from __future__ import annotations

import argparse
import sys

from . import backtest as backtest_mod
from . import costs as costs_mod
from . import phase as phase_mod
from .collector import TIMEFRAMES, calibrate_costs, collect_once
from .demo import sine_candles, synthetic_candles
from .config import Config
from .costs import CostModel
from .exchange.bitso import BitsoClient, BitsoError
from .paper import PaperEngine
from .risk import RiskManager
from .storage import Store
from .strategy.sma_cross import BuyAndHold, SmaCross


def _client(cfg: Config) -> BitsoClient:
    return BitsoClient(cfg.credentials)


def cmd_books(cfg: Config, args) -> int:
    for book in _client(cfg).available_books():
        print(
            f"{book['book']:<12} "
            f"min {book.get('minimum_value', '?'):>10} "
            f"max {book.get('maximum_value', '?'):>14}"
        )
    return 0


def cmd_spread(cfg: Config, args) -> int:
    bps = _client(cfg).spread_bps(args.book)
    costs = cfg.costs
    print(f"Spread actual de {args.book}: {bps:.1f} bps ({bps / 100:.3f} %)")
    print(f"Costo ida y vuelta modelado: {costs.breakeven_move_pct():.2f} %")
    print(
        "Una estrategia tiene que capturar mas que eso por operacion, "
        "solo para empatar."
    )
    return 0


def cmd_collect(cfg: Config, args) -> int:
    with Store(cfg.db_path) as store:
        stats = collect_once(_client(cfg), store, args.book, limit=args.limit)
    print(
        f"trades nuevos: {stats['new_trades']} "
        f"(total {stats['total_trades']}) -> velas: "
        + ", ".join(f"{k}={stats[k]}" for k in TIMEFRAMES)
    )
    return 0


def cmd_calibrate(cfg: Config, args) -> int:
    import time

    values = calibrate_costs(_client(cfg), args.book)
    with Store(cfg.db_path) as store:
        store.save_calibration(
            book=args.book,
            ts=int(time.time()),
            half_spread_bps=values["half_spread_bps"],
            maker_fee_bps=values.get("maker_fee_bps"),
            taker_fee_bps=values.get("taker_fee_bps"),
        )
        samples = store.calibration_samples(args.book)
        model, _ = costs_mod.from_samples(samples, cfg.costs)

    print("Medicion de ahora:")
    for key, value in values.items():
        print(f"  {key} = {value:.2f}")
    if "taker_fee_bps" not in values:
        print("  (las comisiones reales requieren credenciales de solo lectura)")

    print(f"\nModelo efectivo con {len(samples)} muestra(s) guardadas:")
    print(f"  medio spread (mediana)  {model.half_spread_bps:>6.1f} bps")
    print(f"  taker                   {model.taker_fee_bps:>6.1f} bps")
    print(f"  ida y vuelta            {model.round_trip_bps():>6.1f} bps"
          f" = {model.breakeven_move_pct():.2f} %")
    print("\nCorrer esto varias veces al dia: el spread se abre y se cierra, "
          "y una sola muestra puede subestimarlo.")
    return 0


def cmd_balance(cfg: Config, args) -> int:
    if not cfg.credentials.available:
        print(
            "Faltan credenciales. Cargar BITSO_API_KEY y BITSO_API_SECRET "
            "como variables de entorno del entorno de ejecucion.",
            file=sys.stderr,
        )
        return 2
    for currency, data in sorted(_client(cfg).balance().items()):
        total = float(data["total"])
        if total > 0:
            print(f"{currency.upper():<8} {total:>16.8f}")
    return 0


def cmd_costs(cfg: Config, args) -> int:
    costs = cfg.costs
    print(f"  taker            {costs.taker_fee_bps:>6.1f} bps")
    print(f"  maker            {costs.maker_fee_bps:>6.1f} bps")
    print(f"  medio spread     {costs.half_spread_bps:>6.1f} bps")
    print(f"  slippage         {costs.slippage_bps:>6.1f} bps")
    print(f"  ida y vuelta     {costs.round_trip_bps():>6.1f} bps "
          f"= {costs.breakeven_move_pct():.2f} % por operacion")
    capital = cfg.starting_cash
    per_trade = capital * costs.round_trip_bps() / 10_000
    print(f"\nCon {capital:.2f} de capital: {per_trade:.3f} por operacion completa.")
    print(f"10 operaciones al mes = {per_trade * 10:.2f} "
          f"({per_trade * 10 / capital:.1%} del capital).")
    return 0


def cmd_demo(cfg: Config, args) -> int:
    """Carga velas sinteticas para verificar el pipeline sin red."""
    tf = TIMEFRAMES[args.tf]
    generator = sine_candles if args.shape == "sine" else synthetic_candles
    candles = generator(n=args.n, tf=tf)
    book = f"DEMO_{args.shape}"
    with Store(cfg.db_path) as store:
        store.upsert_candles(book, tf, candles)
    print(f"{len(candles)} velas sinteticas cargadas en el libro '{book}' ({args.tf}).")
    print("ATENCION: son datos inventados. No sirven para evaluar estrategias.")
    print(f"\nProbar con:\n  python -m tradingbot --book {book} backtest --tf {args.tf}")
    return 0


def _strategy_and_costs(cfg: Config, store: Store, args):
    """Estrategia configurada y costos medidos, si los hay."""
    strategy = SmaCross(args.fast, args.slow)
    model, calibrated = costs_mod.from_samples(
        store.calibration_samples(args.book), cfg.costs
    )
    return strategy, model, calibrated


def cmd_gate(cfg: Config, args) -> int:
    """Responde si el criterio de salida de la fase se cumple."""
    with Store(cfg.db_path) as store:
        strategy, model, calibrated = _strategy_and_costs(cfg, store, args)
        run_id = args.run_id or phase_mod.run_id_for_paper(
            args.book, TIMEFRAMES[args.tf], strategy
        )
        result = phase_mod.evaluate(store, args.book, strategy, run_id=run_id)

    print(f"Corrida: {result.run_id}")
    print(f"Costos:  {'medidos' if calibrated else 'ESTIMADOS (correr calibrate)'}"
          f" · ida y vuelta {model.breakeven_move_pct():.2f} %")
    print()
    print("Historia disponible por timeframe:")
    for row in result.readiness:
        mark = "listo" if row.ready else f"faltan {row.missing}"
        eta = "" if row.ready else f"  ({phase_mod.humanize_eta(row.eta_seconds)})"
        print(f"  {row.label:<4} {row.candles:>6} velas / {row.warmup} warmup"
              f"   {mark}{eta}")
    print()
    print(f"Operaciones completas: {result.round_trips} de {result.required}"
          f"  ({result.progress:.0%})")
    if result.round_trips:
        print(f"Expectancy por operacion: {result.expectancy:+.4f}")
        print(f"Win rate: {result.win_rate:.1f} %")
        print(f"Comisiones pagadas: {result.fees_paid:.4f}")
    print()
    print(f"VEREDICTO: {result.verdict.upper()}")
    print(f"  {result.reason}")
    return 0 if result.passed else 1


def cmd_paper(cfg: Config, args) -> int:
    """Procesa a mano las velas cerradas pendientes del motor de papel."""
    tf = TIMEFRAMES[args.tf]
    with Store(cfg.db_path) as store:
        strategy, model, calibrated = _strategy_and_costs(cfg, store, args)
        if not calibrated:
            print("AVISO: costos estimados, no medidos. Correr 'calibrate'.",
                  file=sys.stderr)
        engine = PaperEngine(
            store=store,
            book=args.book,
            tf=tf,
            strategy=strategy,
            starting_cash=cfg.starting_cash,
            costs=model,
            risk=RiskManager(
                cfg.max_position_pct, cfg.max_daily_loss_pct, cfg.min_order_notional
            ),
        )
        result = engine.step()

    print(f"run_id: {engine.run_id}")
    print(f"  velas procesadas   {result.processed}")
    print(f"  operaciones        {result.fills}")
    print(f"  rechazos           {result.rejections}")
    print(f"  equity             {result.equity:.4f}")
    if result.halted:
        print("  DETENIDO por el kill switch; requiere intervencion manual.")
    return 0


def cmd_backtest(cfg: Config, args) -> int:
    tf = TIMEFRAMES[args.tf]
    with Store(cfg.db_path) as store:
        candles = store.load_candles(args.book, tf)
        if len(candles) < 2:
            print(
                f"No hay velas de {args.tf} para {args.book}. "
                "Correr 'collect' primero y dejarlo acumulando datos.",
                file=sys.stderr,
            )
            return 2

        strategies = [SmaCross(args.fast, args.slow), BuyAndHold()]
        for strategy in strategies:
            if len(candles) < strategy.warmup:
                print(f"\n{strategy.name}: datos insuficientes "
                      f"({len(candles)} velas, necesita {strategy.warmup})")
                continue
            result = backtest_mod.run(
                candles,
                strategy,
                starting_cash=cfg.starting_cash,
                costs=cfg.costs,
                risk=RiskManager(
                    cfg.max_position_pct,
                    cfg.max_daily_loss_pct,
                    cfg.min_order_notional,
                ),
                store=store,
                book=args.book,
            )
            print(f"\n{strategy.name}  [{result.run_id}]  {len(candles)} velas")
            print(result.metrics.render())
            if result.halted:
                print(f"  DETENIDO: {result.halt_reason}")
            if result.rejections:
                print(f"  ordenes rechazadas por riesgo: {len(result.rejections)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tradingbot")
    parser.add_argument("--book", default=None, help="par de mercado, ej. usdc_ars")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("books", help="lista los pares disponibles y sus minimos")
    sub.add_parser("costs", help="muestra el modelo de costos y su impacto")
    sub.add_parser("balance", help="balance de la cuenta (requiere credenciales)")
    sub.add_parser("spread", help="spread real del libro, medido ahora")
    sub.add_parser("calibrate", help="mide spread y comisiones reales")

    collect = sub.add_parser("collect", help="baja trades y arma velas")
    collect.add_argument("--limit", type=int, default=100)

    demo = sub.add_parser("demo", help="carga datos sinteticos (sin red)")
    demo.add_argument("--shape", choices=["random", "sine"], default="random")
    demo.add_argument("--n", type=int, default=500)
    demo.add_argument("--tf", choices=sorted(TIMEFRAMES), default="1h")

    bt = sub.add_parser("backtest", help="corre el backtest sobre datos guardados")
    bt.add_argument("--tf", choices=sorted(TIMEFRAMES), default="1h")
    bt.add_argument("--fast", type=int, default=10)
    bt.add_argument("--slow", type=int, default=30)

    gate = sub.add_parser("gate", help="evalua el criterio de salida de la fase")
    gate.add_argument("--tf", choices=sorted(TIMEFRAMES), default="1h")
    gate.add_argument("--fast", type=int, default=10)
    gate.add_argument("--slow", type=int, default=30)
    gate.add_argument("--run-id", default=None, dest="run_id")

    paper = sub.add_parser("paper", help="procesa velas cerradas en papel")
    paper.add_argument("--tf", choices=sorted(TIMEFRAMES), default="1h")
    paper.add_argument("--fast", type=int, default=10)
    paper.add_argument("--slow", type=int, default=30)

    return parser


HANDLERS = {
    "books": cmd_books,
    "spread": cmd_spread,
    "collect": cmd_collect,
    "calibrate": cmd_calibrate,
    "balance": cmd_balance,
    "costs": cmd_costs,
    "backtest": cmd_backtest,
    "demo": cmd_demo,
    "gate": cmd_gate,
    "paper": cmd_paper,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = Config.from_env(**({"book": args.book} if args.book else {}))
    if not getattr(args, "book", None):
        args.book = cfg.book
    try:
        return HANDLERS[args.command](cfg, args)
    except BitsoError as exc:
        print(f"Error de Bitso: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
