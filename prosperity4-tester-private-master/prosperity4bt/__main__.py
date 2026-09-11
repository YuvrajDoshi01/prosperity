import sys
from datetime import datetime
from typer import Argument, Option, Typer
from typing import Annotated, Optional
from pathlib import Path
from prosperity4bt.back_tester import BackTester
from prosperity4bt.models.test_options import TestOptions, TradeMatchingMode, MatchMode, ExtraFlowMode

app = Typer(context_settings={"help_option_names": ["--help", "-h"]})

@app.command()
def run(
    algorithm: Annotated[Path, Argument(help="Path to the Python file containing the algorithm to backtest.", show_default=False,exists=True, file_okay=True, dir_okay=False, resolve_path=True)],
    days: Annotated[list[str], Argument(help="The days to backtest on. <round>-<day> for a single day, <round> for all days in a round.", show_default=False)],
    out: Annotated[Optional[Path], Option(help="File to save output log to (defaults to backtests/<timestamp>.log).", show_default=False, dir_okay=False, resolve_path=True)] = None,
    no_out: Annotated[bool, Option("--no-out", help="Skip saving output log.")] = False,
    data: Annotated[Optional[Path], Option(help="Path to data directory.", show_default=False, exists=True, file_okay=False, dir_okay=True, resolve_path=True)] = None,
    print_output: Annotated[bool, Option("--print", help="Print the trader's output to stdout while it's running.")] = False,
    match_trades: Annotated[TradeMatchingMode, Option(help="How to match orders against market trades. 'all' matches trades with prices equal to or worse than your quotes, 'worse' matches trades with prices worse than your quotes, 'none' does not match trades against orders at all.")] = TradeMatchingMode.all,
    no_progress: Annotated[bool, Option("--no-progress", help="Don't show progress bars.")] = False,
    merge_pnl: Annotated[bool, Option("--merge-pnl", help="Merge profit and loss across days.")] = True,
    vis: Annotated[bool, Option("--vis", help="Open backtest results in https://jmerle.github.io/imc-prosperity-3-visualizer/ when done.")] = False,
    original_timestamps: Annotated[bool, Option("--original-timestamps", help="Preserve original timestamps in output log rather than making them increase across days.")] = False,
    ticks: Annotated[Optional[int], Option("--ticks", help="Maximum number of ticks to simulate per day.")] = None,
    iterations: Annotated[Optional[int], Option("--iterations", help="Number of times run() is called per day. Simulates test (1000) or final (10000) scoring cadence. Between calls, resting orders persist.")] = None,
    match_mode: Annotated[MatchMode, Option("--match-mode", help="Matching mode: 'default' (>= crossing, CSV-trade fallback) or 'imc' (== exact + calibrated taker supplement, recommended for website ranking).")] = MatchMode.default,
    extra_flow: Annotated[ExtraFlowMode, Option("--extra-flow", help="Simulate R2 MAF extra 25% flow. 'none' = no change (80% testing case); 'scale' = multiply volumes by 1.25; 'interp' = inject new levels at midpoints.")] = ExtraFlowMode.none,
):
    if out is not None and no_out:
        print("Error: --out and --no-out are mutually exclusive")
        sys.exit(1)

    options = TestOptions(algorithm, days, __parse_out(out, no_out))
    options.back_data_dir = data
    options.print_output = print_output
    options.trade_matching_mode = match_trades
    options.show_progress = not no_progress
    options.merge_profit_loss = merge_pnl
    options.show_visualizer = vis
    options.merge_timestamps = not original_timestamps
    options.max_ticks = ticks
    options.iterations = iterations
    options.match_mode = match_mode
    options.extra_flow = extra_flow

    back_tester = BackTester(options)
    back_tester.run()


def __parse_out(out: Optional[Path], no_out: bool) -> Optional[Path]:
    if out is not None:
        return out

    if no_out:
        return None

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return Path.cwd() / "backtests" / f"{timestamp}.log"


def main() -> None:
    app()

if __name__ == "__main__":
    main()