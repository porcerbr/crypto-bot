"""Limpeza e validação de dados de mercado.

Remove outliers, preenche gaps, valida consistência
para evitar que dados ruins gerem sinais falsos.
"""
import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger("DataCleaner")


class DataCleaner:
    """Pipeline de limpeza de dados OHLCV."""

    def process(self, df: pd.DataFrame) -> Optional[pd.DataFrame]:
        """Executa pipeline completo de limpeza.

        Steps:
        1. Remove duplicatas
        2. Ordena por tempo
        3. Remove valores nulos críticos
        4. Detecta e corrige outliers de preço
        5. Valida consistência OHLC
        6. Preenche gaps menores
        """
        try:
            df = df.copy()

            # 1. Duplicatas
            if "datetime" in df.columns:
                df = df.drop_duplicates(subset=["datetime"])
            elif "date" in df.columns:
                df = df.drop_duplicates(subset=["date"])

            # 2. Ordenar
            time_col = "datetime" if "datetime" in df.columns else "date"
            df = df.sort_values(by=time_col).reset_index(drop=True)

            # 3. Remover nulos em colunas críticas
            df = df.dropna(subset=["open", "high", "low", "close"])

            # 4. Outliers: remover candles com variação > 20% em 1 período
            df["returns"] = df["close"].pct_change().abs()
            df = df[df["returns"] < 0.20].drop(columns=["returns"])

            # 5. Consistência OHLC
            df["high"] = df[["open", "high", "low", "close"]].max(axis=1)
            df["low"] = df[["open", "high", "low", "close"]].min(axis=1)

            # 6. Volume: preencher com média móvel
            if "volume" in df.columns:
                df["volume"] = df["volume"].fillna(df["volume"].rolling(5, min_periods=1).mean())
                df["volume"] = df["volume"].clip(lower=0)

            logger.info(f"Limpeza concluída: {len(df)} registros válidos")
            return df

        except Exception as e:
            logger.error(f"Erro na limpeza de dados: {e}")
            return None
