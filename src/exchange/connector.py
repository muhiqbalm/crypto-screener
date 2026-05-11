"""
Exchange Connector Module

Manages connection to cryptocurrency exchanges via CCXT library.
"""

import logging
import ccxt

logger = logging.getLogger(__name__)


class ExchangeConnector:
    """
    Manages connection to OKX exchange via CCXT library.
    
    This class initializes and validates the connection to OKX exchange,
    ensuring that Binance is NOT used (per regional restrictions).
    """
    
    def __init__(self, exchange_id: str = 'okx'):
        """
        Initialize CCXT exchange instance.
        
        Args:
            exchange_id: Exchange identifier (default: 'okx')
            
        Raises:
            ValueError: If exchange_id is 'binance' (blocked exchange)
        """
        # Validate that Binance is NOT used
        if exchange_id.lower() == 'binance':
            error_msg = "Binance exchange is not allowed due to regional restrictions"
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        self.exchange_id = exchange_id
        self.exchange = None
        logger.info(f"ExchangeConnector initialized with exchange: {exchange_id}")
    
    def connect(self) -> bool:
        """
        Establish connection to the exchange and validate availability.
        
        Returns:
            bool: True if connection successful, False otherwise
            
        Raises:
            ConnectionError: If connection to exchange fails
        """
        try:
            # Initialize the exchange instance
            logger.info(f"Attempting to connect to {self.exchange_id} exchange...")
            
            # Get the exchange class dynamically
            if not hasattr(ccxt, self.exchange_id):
                raise ValueError(f"Exchange '{self.exchange_id}' is not supported by CCXT")
            
            exchange_class = getattr(ccxt, self.exchange_id)
            self.exchange = exchange_class()
            
            # Load markets to validate connection
            self.exchange.load_markets()
            
            logger.info(f"Successfully connected to {self.exchange_id} exchange")
            logger.info(f"Loaded {len(self.exchange.markets)} markets")
            return True
            
        except ccxt.NetworkError as e:
            error_msg = f"Network error connecting to {self.exchange_id} exchange: {e}"
            logger.error(error_msg)
            raise ConnectionError(error_msg)
            
        except ccxt.ExchangeError as e:
            error_msg = f"{self.exchange_id} exchange error: {e}"
            logger.error(error_msg)
            raise ConnectionError(error_msg)
            
        except Exception as e:
            error_msg = f"Unexpected error connecting to {self.exchange_id} exchange: {e}"
            logger.error(error_msg)
            raise ConnectionError(error_msg)
    
    def get_exchange(self) -> ccxt.Exchange:
        """
        Return the configured exchange instance.
        
        Returns:
            ccxt.Exchange: The configured exchange instance
            
        Raises:
            RuntimeError: If exchange is not connected (connect() not called)
        """
        if self.exchange is None:
            error_msg = "Exchange not connected. Call connect() first."
            logger.error(error_msg)
            raise RuntimeError(error_msg)
        
        return self.exchange
