"""
Exchange Connector Module

Manages connection to cryptocurrency exchanges via CCXT library.
"""

import logging
import ccxt

logger = logging.getLogger(__name__)


class ExchangeConnector:
    """
    Manages connection to cryptocurrency exchanges via CCXT library.
    
    Supports Binance USDT-M Futures exchange.
    """
    
    # Supported exchanges (OKX removed due to API compatibility issues)
    SUPPORTED_EXCHANGES = ['binance', 'binanceusdm']
    
    # Blocked exchanges
    BLOCKED_EXCHANGES = ['okx']
    
    def __init__(self, exchange_id: str = 'binanceusdm'):
        """
        Initialize CCXT exchange instance.
        
        Args:
            exchange_id: Exchange identifier. Supported: 'binance', 'binanceusdm'
                        Default: 'binanceusdm' (Binance USDT-M Futures)
            
        Raises:
            ValueError: If exchange_id is not supported or is blocked
        """
        # Check if exchange is blocked
        if exchange_id.lower() in self.BLOCKED_EXCHANGES:
            error_msg = f"OKX exchange is not allowed due to API compatibility issues. Use 'binanceusdm' instead."
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        if exchange_id.lower() not in self.SUPPORTED_EXCHANGES:
            error_msg = f"Exchange '{exchange_id}' not supported. Use one of: {self.SUPPORTED_EXCHANGES}"
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        self.exchange_id = exchange_id.lower()
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
