"""
Ranking Engine Module

Ranks assets by multi-factor score.
"""

import logging
import pandas as pd

logger = logging.getLogger(__name__)


class RankingEngine:
    """
    Ranks assets by multi-factor score.
    
    This class sorts assets in descending order by their multi-factor scores
    and assigns ranking positions. The ranking uses a stable sort algorithm
    to preserve the relative order of assets with equal scores.
    
    Ranking Properties:
    - Assets are sorted by multi_factor_score in descending order (highest first)
    - Rank 1 = highest score, Rank 2 = second highest, etc.
    - Stable sort ensures assets with equal scores maintain their original relative order
    - All original DataFrame columns are preserved in the output
    """
    
    def rank_assets(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Sort DataFrame by multi_factor_score descending and add rank column.
        
        This method performs the following operations:
        1. Validates that the DataFrame contains a 'multi_factor_score' column
        2. Sorts the DataFrame by 'multi_factor_score' in descending order
        3. Uses stable sort (kind='mergesort') to preserve relative order for equal scores
        4. Adds a 'rank' column with position numbers (1 = highest score)
        5. Returns the sorted DataFrame with all original columns plus rank
        
        Stable Sort Behavior:
        - When two assets have the same multi_factor_score, their relative order
          from the input DataFrame is preserved in the output
        - This ensures deterministic and reproducible ranking results
        - Example: If assets A and B both have score 0.5, and A appears before B
          in the input, then A will appear before B in the output
        
        Args:
            df: DataFrame with 'multi_factor_score' column and other asset data
            
        Returns:
            pd.DataFrame: Sorted DataFrame with added 'rank' column
                - All original columns are preserved
                - Sorted by multi_factor_score descending
                - 'rank' column contains position numbers (1, 2, 3, ...)
                
        Raises:
            KeyError: If 'multi_factor_score' column is missing from DataFrame
        """
        # Validate required column exists
        if 'multi_factor_score' not in df.columns:
            error_msg = "DataFrame must contain 'multi_factor_score' column"
            logger.error(error_msg)
            raise KeyError(error_msg)
        
        # Handle empty DataFrame
        if len(df) == 0:
            logger.warning("Empty DataFrame provided to rank_assets")
            # Return empty DataFrame with rank column added
            df_ranked = df.copy()
            df_ranked['rank'] = pd.Series(dtype=int)
            return df_ranked
        
        # Sort DataFrame by multi_factor_score in descending order
        # Use stable sort (kind='mergesort') to preserve relative order for equal scores
        # ascending=False means highest scores come first
        df_sorted = df.sort_values(
            by='multi_factor_score',
            ascending=False,
            kind='mergesort',  # Stable sort algorithm
            ignore_index=False  # Preserve original index
        ).reset_index(drop=True)  # Reset index to get clean sequential indices
        
        # Add rank column with position numbers (1 = highest score)
        # rank = index + 1 (since index starts at 0)
        df_sorted['rank'] = range(1, len(df_sorted) + 1)
        
        # Log ranking results
        logger.info(f"Ranked {len(df_sorted)} assets by multi-factor score")
        if len(df_sorted) > 0:
            top_score = df_sorted.iloc[0]['multi_factor_score']
            bottom_score = df_sorted.iloc[-1]['multi_factor_score']
            logger.debug(f"Top ranked score: {top_score:.4f}, Bottom ranked score: {bottom_score:.4f}")
        
        return df_sorted
