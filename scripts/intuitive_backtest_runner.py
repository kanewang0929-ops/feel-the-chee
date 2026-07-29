#!/usr/bin/env python3
"""Run the intuitive backtest against the corrected runtime module."""
import sys
import intuitive_agent_runtime as runtime

sys.modules["intuitive_agent"] = runtime

import intuitive_backtest


if __name__ == "__main__":
    intuitive_backtest.main()
