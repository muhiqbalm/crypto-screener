"""
Dashboard Builder Module

Builds complete visualization dashboard with multiple panels.
"""

import logging
import pandas as pd
import matplotlib.pyplot as plt
from .panels import MultiFactorPanel, FundingRatePanel, LongShortRatioPanel

logger = logging.getLogger(__name__)


class DashboardBuilder:
    """
    Builds complete visualization dashboard with three panels.
    
    This class coordinates the creation of a comprehensive dashboard displaying:
    1. Multi-factor scores (top panel)
    2. Funding rates (middle panel)
    3. Long/short ratios (bottom panel)
    
    All three panels share a common Y-axis showing asset symbols ordered by
    multi-factor score (highest to lowest). This consistent ordering enables
    easy visual comparison across different metrics.
    
    The dashboard uses matplotlib's subplot functionality to create a vertical
    stack of three panels with proper spacing and shared axes.
    """
    
    def __init__(self, df: pd.DataFrame):
        """
        Initialize DashboardBuilder with ranked DataFrame.
        
        Args:
            df: Ranked DataFrame containing all required columns:
                - 'symbol': Asset symbol (str)
                - 'multi_factor_score': Composite score (float)
                - 'tier': Tier classification ('A' or 'B')
                - 'funding_rate': Funding rate percentage (float)
                - 'long_short_ratio': Long/short ratio (float)
                
                The DataFrame should already be sorted by multi_factor_score
                in descending order (from RankingEngine).
        
        Raises:
            KeyError: If required columns are missing from DataFrame
        """
        # Validate required columns exist
        required_columns = ['symbol', 'multi_factor_score', 'tier', 
                          'funding_rate', 'long_short_ratio']
        missing_columns = [col for col in required_columns if col not in df.columns]
        
        if missing_columns:
            error_msg = f"DataFrame missing required columns for DashboardBuilder: {missing_columns}"
            logger.error(error_msg)
            raise KeyError(error_msg)
        
        self.df = df
        self.figure = None
        
        logger.info(f"DashboardBuilder initialized with {len(df)} assets")
    
    def create_dashboard(self):
        """
        Create 3-panel figure with shared Y-axis.
        
        Dashboard Layout:
        - Vertical stack of 3 panels (subplots)
        - Panel 1 (top): Multi-factor scores
        - Panel 2 (middle): Funding rates
        - Panel 3 (bottom): Long/short ratios
        - Shared Y-axis: Asset symbols ordered by multi-factor score
        - Figure size: 12 inches wide x 10 inches tall (suitable for display/print)
        
        The method creates the figure, renders all three panels by calling their
        respective render() methods, and applies tight_layout() for proper spacing.
        
        Returns:
            matplotlib.figure.Figure: The complete dashboard figure
            
        Raises:
            ValueError: If DataFrame is empty or missing required data
            RuntimeError: If matplotlib rendering fails
            Exception: If visualization rendering fails for other reasons
        """
        try:
            # Log warning if DataFrame is empty, but continue to create empty panels
            if len(self.df) == 0:
                logger.warning("Creating dashboard with empty DataFrame (no assets to visualize)")
            else:
                logger.info(f"Creating dashboard with 3 panels for {len(self.df)} assets...")
            
            # Create figure with 3 subplots in vertical stack
            # figsize=(width, height) in inches
            # - Width: 12 inches provides good horizontal space for labels and bars
            # - Height: 10 inches (3-4 inches per panel) provides good vertical space
            # sharex=False: Each panel has independent X-axis (different metrics)
            # sharey=True: All panels share Y-axis (same asset ordering)
            try:
                fig, axes = plt.subplots(
                    nrows=3,           # 3 panels stacked vertically
                    ncols=1,           # Single column
                    figsize=(12, 10),  # Figure size in inches
                    sharex=False,      # Independent X-axes (different metrics)
                    sharey=True        # Shared Y-axis (same asset ordering)
                )
            except Exception as e:
                error_msg = f"Failed to create matplotlib figure: {e}. Check matplotlib installation and display backend."
                logger.error(error_msg)
                raise RuntimeError(error_msg)
            
            # Store figure reference
            self.figure = fig
            
            # Render Panel 1: Multi-Factor Score (top panel)
            try:
                logger.info("Rendering multi-factor score panel...")
                multi_factor_panel = MultiFactorPanel()
                multi_factor_panel.render(axes[0], self.df)
                logger.info("Multi-factor score panel rendered successfully")
            except KeyError as e:
                error_msg = f"Failed to render multi-factor score panel: Missing required data column - {e}"
                logger.error(error_msg)
                raise ValueError(error_msg)
            except Exception as e:
                error_msg = f"Failed to render multi-factor score panel: {e}"
                logger.error(error_msg)
                raise RuntimeError(error_msg)
            
            # Render Panel 2: Funding Rate (middle panel)
            try:
                logger.info("Rendering funding rate panel...")
                funding_rate_panel = FundingRatePanel()
                funding_rate_panel.render(axes[1], self.df)
                logger.info("Funding rate panel rendered successfully")
            except KeyError as e:
                error_msg = f"Failed to render funding rate panel: Missing required data column - {e}"
                logger.error(error_msg)
                raise ValueError(error_msg)
            except Exception as e:
                error_msg = f"Failed to render funding rate panel: {e}"
                logger.error(error_msg)
                raise RuntimeError(error_msg)
            
            # Render Panel 3: Long/Short Ratio (bottom panel)
            try:
                logger.info("Rendering long/short ratio panel...")
                long_short_panel = LongShortRatioPanel()
                long_short_panel.render(axes[2], self.df)
                logger.info("Long/short ratio panel rendered successfully")
            except KeyError as e:
                error_msg = f"Failed to render long/short ratio panel: Missing required data column - {e}"
                logger.error(error_msg)
                raise ValueError(error_msg)
            except Exception as e:
                error_msg = f"Failed to render long/short ratio panel: {e}"
                logger.error(error_msg)
                raise RuntimeError(error_msg)
            
            # Apply tight_layout() for proper spacing between panels
            # This automatically adjusts subplot parameters to give specified padding
            # and avoid overlapping labels, titles, and axes
            # pad: Padding between the figure edge and the edges of subplots (in font-size units)
            # h_pad: Height padding between subplots (in font-size units)
            try:
                fig.tight_layout(pad=2.0, h_pad=3.0)
            except Exception as e:
                # tight_layout can fail with certain figure configurations
                # Log warning but don't fail the entire dashboard creation
                logger.warning(f"Failed to apply tight_layout (non-critical): {e}")
            
            logger.info("Dashboard creation complete")
            
            return fig
            
        except (ValueError, RuntimeError) as e:
            # Re-raise specific exceptions with context preserved
            raise
        except Exception as e:
            error_msg = f"Unexpected error during dashboard creation: {e}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)
    
    def save_dashboard(self, filepath: str):
        """
        Save figure to disk.
        
        This method saves the dashboard figure to a file on disk. The file format
        is automatically determined from the filepath extension (e.g., .png, .pdf, .svg).
        
        Common formats:
        - PNG: Raster format, good for web display and presentations
        - PDF: Vector format, good for printing and publications
        - SVG: Vector format, good for web and editing in vector graphics software
        
        Args:
            filepath: Path where the figure should be saved (e.g., 'dashboard.png')
                     The file extension determines the output format.
        
        Raises:
            RuntimeError: If create_dashboard() has not been called yet
            ValueError: If filepath is invalid or empty
            PermissionError: If file cannot be written due to permissions
            OSError: If file saving fails due to disk/path issues
        """
        # Validate that dashboard has been created
        if self.figure is None:
            error_msg = "Dashboard not created yet. Call create_dashboard() first."
            logger.error(error_msg)
            raise RuntimeError(error_msg)
        
        # Validate filepath is not empty
        if not filepath or not filepath.strip():
            error_msg = "Filepath cannot be empty"
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        try:
            logger.info(f"Saving dashboard to {filepath}...")
            
            # Validate file extension is supported
            import os
            _, ext = os.path.splitext(filepath)
            supported_formats = ['.png', '.pdf', '.svg', '.jpg', '.jpeg']
            if ext.lower() not in supported_formats:
                logger.warning(f"File extension '{ext}' may not be supported. Supported formats: {supported_formats}")
            
            # Save figure to disk
            # dpi: Dots per inch (resolution) - 300 is high quality for printing
            # bbox_inches='tight': Trim whitespace around the figure
            # facecolor='white': Set background color to white (default is transparent)
            self.figure.savefig(
                filepath,
                dpi=300,              # High resolution for quality output
                bbox_inches='tight',  # Trim whitespace
                facecolor='white'     # White background
            )
            
            logger.info(f"Dashboard successfully saved to {filepath}")
            
        except PermissionError as e:
            error_msg = f"Permission denied: Cannot write to {filepath}. Check file permissions and ensure the file is not open in another program."
            logger.error(error_msg)
            raise PermissionError(error_msg)
        except OSError as e:
            error_msg = f"Failed to save dashboard to {filepath}: {e}. Check that the directory exists and disk space is available."
            logger.error(error_msg)
            raise OSError(error_msg)
        except Exception as e:
            error_msg = f"Unexpected error saving dashboard to {filepath}: {e}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)


def main():
    """
    Main execution flow for the crypto screener system.
    
    Pipeline stages:
    1. Validate dependencies (completed at import time)
    2. Initialize exchange connector and establish connection
    3. Fetch market data for symbol list
    4. Generate signals and calculate scores
    5. Rank assets
    6. Generate visualization
    7. Save dashboard to disk with timestamp
    
    Each stage is wrapped in try-except blocks for appropriate error handling.
    Errors are logged and the system exits gracefully with descriptive messages.
    
    Requirements: 9.4, 9.5
    """
    logger.info("=" * 70)
    logger.info("Starting Crypto Screener System")
    logger.info("=" * 70)
    
    # Define symbol list for perpetual futures contracts
    SYMBOLS = [
        'BTC/USDT:USDT',
        'ETH/USDT:USDT',
        'ZEC/USDT:USDT',
        'TAO/USDT:USDT',
        'TON/USDT:USDT',
        'AAVE/USDT:USDT',
        'SOL/USDT:USDT'
    ]
    
    logger.info(f"Target symbols: {SYMBOLS}")
    
    # Stage 1: Initialize ExchangeConnector and establish connection
    try:
        logger.info("\n" + "=" * 70)
        logger.info("Stage 1: Initializing exchange connection")
        logger.info("=" * 70)
        
        connector = ExchangeConnector(exchange_id='okx')
        connector.connect()
        exchange = connector.get_exchange()
        
        logger.info("[SUCCESS] Exchange connection established successfully")
        
    except ConnectionError as e:
        logger.error(f"[FAILED] Failed to connect to exchange: {e}")
        logger.error("System cannot proceed without exchange connection")
        sys.exit(1)
    except Exception as e:
        logger.error(f"[FAILED] Unexpected error during exchange initialization: {e}")
        sys.exit(1)
    
    # Stage 2: Create MarketDataFetcher and fetch all data
    try:
        logger.info("\n" + "=" * 70)
        logger.info("Stage 2: Fetching market data")
        logger.info("=" * 70)
        
        fetcher = MarketDataFetcher(exchange=exchange, symbols=SYMBOLS)
        market_data_df = fetcher.fetch_all_data()
        
        # Log summary of fetched data
        successful_fetches = market_data_df['price'].notna().sum()
        logger.info(f"[SUCCESS] Market data fetch complete: {successful_fetches}/{len(SYMBOLS)} symbols successful")
        
        # Check if we have at least some data to proceed
        if successful_fetches == 0:
            logger.error("[FAILED] No market data could be fetched for any symbol")
            logger.error("System cannot proceed without market data")
            sys.exit(1)
        
        logger.info(f"\nFetched data preview:\n{market_data_df.to_string()}")
        
    except Exception as e:
        logger.error(f"[FAILED] Failed to fetch market data: {e}")
        sys.exit(1)
    
    # Stage 3: Create SignalGenerator and generate signals
    try:
        logger.info("\n" + "=" * 70)
        logger.info("Stage 3: Generating trading signals")
        logger.info("=" * 70)
        
        signal_generator = SignalGenerator()
        
        # Calculate reversal signal
        reversal_signal = signal_generator.calculate_reversal_signal(market_data_df)
        logger.info("[SUCCESS] Reversal signal calculated")
        
        # Calculate momentum signal
        momentum_signal = signal_generator.calculate_momentum_signal(market_data_df)
        logger.info("[SUCCESS] Momentum signal calculated")
        
        # Normalize signals
        reversal_signal_norm = signal_generator.normalize_signal(reversal_signal)
        momentum_signal_norm = signal_generator.normalize_signal(momentum_signal)
        logger.info("[SUCCESS] Signals normalized")
        
        # Add normalized signals to DataFrame
        market_data_df['reversal_signal'] = reversal_signal_norm
        market_data_df['momentum_signal'] = momentum_signal_norm
        
        logger.info(f"\nSignals preview:\n{market_data_df[['symbol', 'reversal_signal', 'momentum_signal']].to_string()}")
        
    except Exception as e:
        logger.error(f"[FAILED] Failed to generate signals: {e}")
        sys.exit(1)
    
    # Stage 4: Create ICWeightCalculator and MultiFactorScorer
    try:
        logger.info("\n" + "=" * 70)
        logger.info("Stage 4: Calculating multi-factor scores")
        logger.info("=" * 70)
        
        # Initialize IC weight calculator
        ic_calculator = ICWeightCalculator()
        logger.info("[SUCCESS] IC weight calculator initialized")
        
        # Initialize multi-factor scorer
        scorer = MultiFactorScorer(ic_calculator=ic_calculator)
        logger.info("[SUCCESS] Multi-factor scorer initialized")
        
        # Calculate multi-factor scores
        multi_factor_scores = scorer.calculate_score(market_data_df)
        market_data_df['multi_factor_score'] = multi_factor_scores
        logger.info("[SUCCESS] Multi-factor scores calculated")
        
        # Classify tiers
        tiers = scorer.classify_tiers(multi_factor_scores)
        market_data_df['tier'] = tiers
        logger.info("[SUCCESS] Tier classification complete")
        
        logger.info(f"\nScores and tiers preview:\n{market_data_df[['symbol', 'multi_factor_score', 'tier']].to_string()}")
        
    except Exception as e:
        logger.error(f"[FAILED] Failed to calculate multi-factor scores: {e}")
        sys.exit(1)
    
    # Stage 5: Create RankingEngine and rank assets
    try:
        logger.info("\n" + "=" * 70)
        logger.info("Stage 5: Ranking assets")
        logger.info("=" * 70)
        
        ranking_engine = RankingEngine()
        ranked_df = ranking_engine.rank_assets(market_data_df)
        
        logger.info("[SUCCESS] Assets ranked by multi-factor score")
        logger.info(f"\nFinal rankings:\n{ranked_df[['rank', 'symbol', 'multi_factor_score', 'tier']].to_string()}")
        
    except Exception as e:
        logger.error(f"[FAILED] Failed to rank assets: {e}")
        sys.exit(1)
    
    # Stage 6: Create DashboardBuilder and generate visualization
    try:
        logger.info("\n" + "=" * 70)
        logger.info("Stage 6: Generating visualization dashboard")
        logger.info("=" * 70)
        
        dashboard_builder = DashboardBuilder(df=ranked_df)
        figure = dashboard_builder.create_dashboard()
        
        logger.info("[SUCCESS] Dashboard visualization created")
        
    except ValueError as e:
        logger.error(f"[FAILED] Visualization failed due to invalid data: {e}")
        logger.error("This may be caused by missing required columns or empty dataset")
        sys.exit(1)
    except RuntimeError as e:
        logger.error(f"[FAILED] Visualization rendering failed: {e}")
        logger.error("This may be caused by matplotlib configuration or display backend issues")
        sys.exit(1)
    except Exception as e:
        logger.error(f"[FAILED] Unexpected error during visualization: {e}")
        sys.exit(1)
    
    # Stage 7: Save dashboard to disk with timestamp in filename
    try:
        logger.info("\n" + "=" * 70)
        logger.info("Stage 7: Saving dashboard to disk")
        logger.info("=" * 70)
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"crypto_screener_dashboard_{timestamp}.png"
        
        dashboard_builder.save_dashboard(filepath=filename)
        
        logger.info(f"[SUCCESS] Dashboard saved to: {filename}")
        
    except PermissionError as e:
        logger.error(f"[FAILED] Permission denied when saving dashboard: {e}")
        logger.error("Check file permissions and ensure the file is not open in another program")
        sys.exit(1)
    except OSError as e:
        logger.error(f"[FAILED] File system error when saving dashboard: {e}")
        logger.error("Check that the directory exists and disk space is available")
        sys.exit(1)
    except Exception as e:
        logger.error(f"[FAILED] Unexpected error saving dashboard: {e}")
        sys.exit(1)
    
    # System completion
    logger.info("\n" + "=" * 70)
    logger.info("Crypto Screener System completed successfully!")
    logger.info("=" * 70)
    logger.info(f"Output file: {filename}")
    logger.info(f"Total assets processed: {len(ranked_df)}")
    logger.info(f"Tier A assets: {(ranked_df['tier'] == 'A').sum()}")
    logger.info(f"Tier B assets: {(ranked_df['tier'] == 'B').sum()}")
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
