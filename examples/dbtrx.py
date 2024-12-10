from argparse import ArgumentParser
import operator
import os
import re

import pandas as pd
import pytz

from qstrader.alpha_model.alpha_model import AlphaModel
from qstrader.alpha_model.fixed_signals import FixedSignalsAlphaModel
from qstrader.asset.equity import Equity
from qstrader.asset.universe.dynamic import DynamicUniverse
from qstrader.asset.universe.static import StaticUniverse
from qstrader.broker.fee_model.percent_fee_model import PercentFeeModel
from qstrader.broker.fee_model.zero_fee_model import ZeroFeeModel
from qstrader.signals.momentum import MomentumSignal
from qstrader.signals.signals_collection import SignalsCollection
from qstrader.data.backtest_data_handler import BacktestDataHandler
from qstrader.data.daily_bar_csv import CSVDailyBarDataSource
from qstrader.statistics.json_statistics import JSONStatistics
from qstrader.statistics.tearsheet import TearsheetStatistics
from qstrader.trading.backtest import BacktestTradingSession


class DBTransactionAlphaModel(AlphaModel):

    def __init__(
        self, signals, mom_lookback, mom_top_n, universe, data_handler
    ):
        """
        Initialise the DBTransactionAlphaModel

        Parameters
        ----------
        signals : `SignalsCollection`
            The entity for interfacing with various pre-calculated
            signals. In this instance we want to use 'momentum'.
        mom_lookback : `integer`
            The number of business days to calculate momentum
            lookback over.
        mom_top_n : `integer`
            The number of assets to include in the portfolio,
            ranking from highest momentum descending.
        universe : `Universe`
            The collection of assets utilised for signal generation.
        data_handler : `DataHandler`
            The interface to the CSV data.

        Returns
        -------
        None
        """
        self.signals = signals
        self.mom_lookback = mom_lookback
        self.mom_top_n = mom_top_n
        self.universe = universe
        self.data_handler = data_handler
        self.gain6m_lookback = 126
        self.gain5d_lookback = 5

    def _highest_momentum_asset(
        self, dt
    ):
        """
        Calculates the ordered list of highest performing momentum
        assets restricted to the 'Top N', for a particular datetime.

        Parameters
        ----------
        dt : `pd.Timestamp`
            The datetime for which the highest momentum assets
            should be calculated.

        Returns
        -------
        `list[str]`
            Ordered list of highest performing momentum assets
            restricted to the 'Top N'.
        """
        assets = self.signals['momentum'].assets
        
        # Calculate the holding-period return momenta for each asset,
        # for the particular provided momentum lookback period
        all_momenta = {
            asset: self.signals['momentum'](
                asset, self.mom_lookback
            ) for asset in assets
        }

        # Obtain a list of the top performing assets by momentum
        # restricted by the provided number of desired assets to
        # trade per month
        return [
            asset[0] for asset in sorted(
                all_momenta.items(),
                key=operator.itemgetter(1),
                reverse=True
            )
        ][:self.mom_top_n]


    def _dbtransaction_asset(
        self, dt
    ):
        """

        Calculates the ordered list of highest performing assets restricted to
        the 'Top N', for a particular datetime.  Assets are ranked by weighted
        avg of 6m gain and 5d loss.

        Parameters
        ----------
        dt : `pd.Timestamp`
            The datetime for which the highest momentum assets
            should be calculated.

        Returns
        -------
        `list[str]`
            Ordered list of highest performing momentum assets
            restricted to the 'Top N'.

        """
        # These are the asset names
        assets6m = self.signals['gain6m'].assets
        assets5d = self.signals['gain5d'].assets
        assert(assets6m == assets5d)

        # Calculate the holding-period return momenta for each asset,
        # for the particular provided momentum lookback period
        all_6m = {
            asset: self.signals['gain6m'](
                asset, self.gain6m_lookback
            ) for asset in assets6m
        }
        all_5d = {
            asset: self.signals['gain5d'](
                asset, self.gain5d_lookback
            ) for asset in assets5d
        }

        # I want to filter anything with tiny volumes

        # These are ordered lists of symbols
        heat = [
            asset[0] for asset in sorted(
                all_6m.items(),
                key=operator.itemgetter(1),
                reverse=True
            )
        ]
        chill = [
            asset[0] for asset in sorted(
                all_5d.items(),
                key=operator.itemgetter(1),
                # reverse=True
            )
        ]
        # Now get the ranks for each symbol, average and resort.
        heatmap = {
            sym:rank for
            sym,rank in zip(heat, list(range(1, len(heat)+1)))
        }
        chillmap = {
            sym:rank for
            sym,rank in zip(chill, list(range(1, len(chill)+1)))
        }
        # Weighted average of each rank signal
        heatwt = 0.5
        dbtrxmap = {
            sym: (heatwt * heatmap[sym] + (1-heatwt)*chillmap[sym])
            for sym in heat
        }

        # Now sort the dbtrx scores to get ordered syms
        dbtrxlist = [
            asset[0] for asset in sorted(
                dbtrxmap.items(),
                key=operator.itemgetter(1),
                #reverse=True    # DBTRX WANTS SMALLEST FIRST
            )
        ]
        # Obtain a list of the top performing assets by dbtransaction score
        # restricted by the provided number of desired assets to trade per
        # month
        #return [
        #    asset[0] for asset in sorted(
        #        dbtrxmap.items(),
        #        key=operator.itemgetter(1),
        #        reverse=True
        #    )
        #][:self.mom_top_n]
        return dbtrxlist[:self.mom_top_n]


    def _generate_signals(
        self, dt, weights
    ):
        """
        Calculate the highest performing momentum for each
        asset then assign 1 / N of the signal weight to each
        of these assets.

        Parameters
        ----------
        dt : `pd.Timestamp`
            The datetime for which the signal weights
            should be calculated.
        weights : `dict{str: float}`
            The current signal weights dictionary.

        Returns
        -------
        `dict{str: float}`
            The newly created signal weights dictionary.
        """
        #top_assets = self._highest_momentum_asset(dt)
        top_assets = self._dbtransaction_asset(dt)
        for asset in top_assets:
            weights[asset] = 1.0 / self.mom_top_n
        return weights

    def __call__(
        self, dt
    ):
        """
        Calculates the signal weights for the top N
        momentum alpha model, assuming that there is
        sufficient data to begin calculating momentum
        on the desired assets.

        Parameters
        ----------
        dt : `pd.Timestamp`
            The datetime for which the signal weights
            should be calculated.

        Returns
        -------
        `dict{str: float}`
            The newly created signal weights dictionary.
        """
        assets = self.universe.get_assets(dt)
        weights = {asset: 0.0 for asset in assets}

        # Only generate weights if the current time exceeds the
        # momentum lookback period
        if self.signals.warmup >= self.mom_lookback:
            weights = self._generate_signals(dt, weights)
        return weights


if __name__ == "__main__":
    # Duration of the backtest
    #start_dt = pd.Timestamp('1998-12-22 14:30:00', tz=pytz.UTC)
    #burn_in_dt = pd.Timestamp('1999-12-22 14:30:00', tz=pytz.UTC)
    #end_dt = pd.Timestamp('2020-12-31 23:59:00', tz=pytz.UTC)

    start_dt = pd.Timestamp('2019-12-22 14:30:00', tz=pytz.UTC)
    burn_in_dt = pd.Timestamp('2020-12-22 14:30:00', tz=pytz.UTC)
    end_dt = pd.Timestamp('2024-10-31 23:59:00', tz=pytz.UTC)
    
    # Model parameters
    gain6m_lookback = 126  # Six months worth of business days
    gain5d_lookback = 5  # 5 business days
    mom_top_n = 3  # Number of assets to include at any one time


    parser = ArgumentParser()
    parser.add_argument("-H", "--heat-window", default=gain6m_lookback, help="heat window")
    parser.add_argument("-C", "--chill-window", default=gain5d_lookback, help="chill window")
    parser.add_argument("-n", "--topn", type=int, default=mom_top_n, help="top N to keep")
    parser.add_argument("-s", "--start-date", type=str,
                        default="1998-12-22",
                        help="First date to process (default 1998-12-22)")
    parser.add_argument("-b", "--burn-in", type=str,
                        default="1y",
                        help="Timespan to use as burn-in")
    parser.add_argument("-e", "--end-date", type=str,
                        default="2020-12-31",
                        help="Last date to process (default 2020-12-31)")
    parser.add_argument("-r", "--rebalance", default="weekly", help="rebalance strategy")
    parser.add_argument("-d", "--rebalance-day", default="MON",
                        help="rebalance day (depends on strategy")
    args = parser.parse_args()

    start_dt = pd.Timestamp(f'{args.start_date} 14:30:00', tz=pytz.UTC)
    end_dt = pd.Timestamp(f'{args.end_date} 23:59:00', tz=pytz.UTC)

    # parse burn-in
    burn_in_dt = start_dt
    m = re.search("(\\d+)y", args.burn_in)
    if m is not None:
        burn_in_dt = burn_in_dt.replace(year=burn_in_dt.year + int(m.group(1)))
    m = re.search("(\\d+)m", args.burn_in)
    if m is not None:
        burn_in_dt = burn_in_dt.replace(month=burn_in_dt.month + int(m.group(1)))
    m = re.search("(\\d+)d", args.burn_in)
    if m is not None:
        burn_in_dt = burn_in_dt.replace(day=burn_in_dt.day + int(m.group(1)))
    print(f"Using burn-in {burn_in_dt}")


    gain6m_lookback = args.heat_window
    gain5d_lookback = args.chill_window
    mom_top_n = args.topn
    kwargs={}
    if args.rebalance == 'weekly':
        kwargs['rebalance_weekday'] = args.rebalance_day
    if args.rebalance == 'monthly':
        kwargs['rebalance_monthday'] = int(args.rebalance_day)

    
    # Construct the symbols and assets necessary for the backtest
    # This utilises the SPDR US sector ETFs, all beginning with XL
    strategy_symbols = ['XL%s' % sector for sector in "BCEFIKPUVY"]
    assets = ['EQ:%s' % symbol for symbol in strategy_symbols]

    # As this is a dynamic universe of assets (XLC is added later)
    # we need to tell QSTrader when XLC can be included. This is
    # achieved using an asset dates dictionary
    asset_dates = {asset: start_dt for asset in assets}
    asset_dates['EQ:XLC'] = pd.Timestamp('2018-06-18 00:00:00', tz=pytz.UTC)
    strategy_universe = DynamicUniverse(asset_dates)

    # To avoid loading all CSV files in the directory, set the
    # data source to load only those provided symbols
    csv_dir = os.environ.get('QSTRADER_CSV_DATA_DIR', '.')
    #strategy_data_source = CSVDailyBarDataSource(csv_dir, Equity, csv_symbols=strategy_symbols, adjust_prices=False)
    strategy_data_source = CSVDailyBarDataSource(
        csv_dir, Equity,
        #csv_symbols=strategy_symbols,
        csv_symbols=None,
        adjust_prices=False)

    # Get asset dates from datasource
    # TODO: use datasource as initial dates, then allow override
    asset_dates = {}
    data = strategy_data_source.asset_bar_frames
    for sym in data.keys():
        asset_dates[sym] = max(data[sym].index[0], start_dt)
    strategy_universe = DynamicUniverse(asset_dates)
    
    strategy_data_handler = BacktestDataHandler(strategy_universe, data_sources=[strategy_data_source])

    # Generate the signals (in this case holding-period return based
    # momentum) used in the top-N momentum alpha model
    gain6m = MomentumSignal(start_dt, strategy_universe, lookbacks=[gain6m_lookback])
    gain5d = MomentumSignal(start_dt, strategy_universe, lookbacks=[gain5d_lookback])
    signals = SignalsCollection({'gain6m': gain6m,
                                 'gain5d': gain5d,
                                 }, strategy_data_handler)

    ## Construct the transaction cost modelling - fees/slippage
    #fee_model = PercentFeeModel(tax_pct=35.0 / 100.0)

    # Generate the alpha model instance for the top-N momentum alpha model
    strategy_alpha_model = DBTransactionAlphaModel(
        signals, gain6m_lookback, mom_top_n, strategy_universe,
        strategy_data_handler
    )

    # Construct the strategy backtest and run it
    strategy_backtest = BacktestTradingSession(
        start_dt,
        end_dt,
        strategy_universe,
        strategy_alpha_model,
        signals=signals,
        #rebalance='end_of_month',
        #rebalance='monthly',
        #rebalance_monthday=6,
        rebalance=args.rebalance,
        #rebalance='weekly',
        #rebalance_weekday='MON',
        long_only=True,
        cash_buffer_percentage=0.01,
        burn_in_dt=burn_in_dt,
        data_handler=strategy_data_handler,
        #fee_model=fee_model,
        **kwargs
    )
    strategy_backtest.run()

    csv_dir = '.' #os.environ.get('QSTRADER_CSV_DATA_DIR', '.')

    # Construct benchmark assets (buy & hold SPY)
    benchmark_symbols = ['SPY']
    benchmark_assets = ['EQ:SPY']
    benchmark_universe = StaticUniverse(benchmark_assets)
    benchmark_data_source = CSVDailyBarDataSource(csv_dir, Equity, csv_symbols=benchmark_symbols, adjust_prices=False)
    benchmark_data_handler = BacktestDataHandler(benchmark_universe, data_sources=[benchmark_data_source])

    ## Construct the transaction cost modelling - fees/slippage
    ## buy and hold is long-term cap gains
    #fee_model = PercentFeeModel(tax_pct=15.0 / 100.0)
    
    # Construct a benchmark Alpha Model that provides
    # 100% static allocation to the SPY ETF, with no rebalance
    benchmark_alpha_model = FixedSignalsAlphaModel({'EQ:SPY': 1.0})
    benchmark_backtest = BacktestTradingSession(
        burn_in_dt,
        end_dt,
        benchmark_universe,
        benchmark_alpha_model,
        rebalance='buy_and_hold',
        long_only=True,
        cash_buffer_percentage=0.01,
        data_handler=benchmark_data_handler,
        #fee_model=fee_model
    )
    benchmark_backtest.run()

    # Performance Output
    #title='US Sector Momentum - Top 3 Sectors'
    title = f"DBTrx n={mom_top_n} p={args.rebalance} d={args.rebalance_day}"
    ofile = f"dbtrx.{args.rebalance}.{args.rebalance}.{args.rebalance_day}.n{mom_top_n}.json"
    jsonstats = JSONStatistics(
        equity_curve=strategy_backtest.get_equity_curve(),
        target_allocations=strategy_backtest.get_target_allocations(),
        benchmark_curve=benchmark_backtest.get_equity_curve(),
        strategy_name=title,
        output_filename=ofile
    )
    jsonstats.to_file()

    tearsheet = TearsheetStatistics(
        strategy_equity=strategy_backtest.get_equity_curve(),
        benchmark_equity=benchmark_backtest.get_equity_curve(),
        title=title
    )
    tearsheet.plot_results()