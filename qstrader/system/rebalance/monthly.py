import pandas as pd
import pytz

from qstrader.system.rebalance.rebalance import Rebalance


class MonthlyRebalance(Rebalance):
    """
    Generates a list of rebalance timestamps for pre- or post-market,
    for a particular trading day of the month between the starting and
    ending dates provided.

    All timestamps produced are set to UTC.

    Parameters
    ----------
    start_date : `pd.Timestamp`
        The starting timestamp of the rebalance range.
    end_date : `pd.Timestamp`
        The ending timestamp of the rebalance range.
    monthday : `int`
        The numeric business day of the month.  Optional, defaults to 0.
    pre_market : `Boolean`, optional
        Whether to carry out the rebalance at market open/close.
    """

    def __init__(
        self,
        start_date,
        end_date,
        monthday=0,
        pre_market=False
    ):
        self.start_date = start_date
        self.end_date = end_date
        # Sets the day of the month
        self.day_of_month = pd.offsets.BDay(monthday)
        self.pre_market_time = self._set_market_time(pre_market)
        self.rebalances = self._generate_rebalances()
        

    def _set_market_time(self, pre_market):
        """
        Determines whether to use market open or market close
        as the rebalance time.

        Parameters
        ----------
        pre_market : `Boolean`
            Whether to use market open or market close
            as the rebalance time.

        Returns
        -------
        `str`
            The string representation of the market time.
        """
        return "14:30:00" if pre_market else "21:00:00"

    def _generate_rebalances(self):
        """
        Output the rebalance timestamp list.

        Returns
        -------
        `list[pd.Timestamp]`
            The list of rebalance timestamps.
        """
        rebalance_dates = pd.date_range(
            start=self.start_date,
            end=self.end_date,
            freq='BMS'
        )
        rebalance_dates = [x + self.day_of_month for x in rebalance_dates]

        rebalance_times = [
            pd.Timestamp(
                "%s %s" % (date, self.pre_market_time), tz=pytz.utc
            )
            for date in rebalance_dates
        ]

        return rebalance_times
